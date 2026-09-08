"""The oracle: turn a change set into a verdict by merging, then validating.

This is the expensive seam of the whole package, and it is assembled from two
injected pieces — a *merge function* and a *validation function* — so that every
part of it can be replaced without touching the search.

The default merge is a plain sequential ``git merge`` in a throwaway worktree:
any textual conflict is a failure, and the conflicting files are recorded. An
**AI-assisted** mode is available (and is intended as the default when running
inside a Claude Code subagent): on a textual conflict a resolver may attempt a
fix under a strict policy — mechanical conflicts only, never a semantic guess —
and the result is *flagged* as "mergeable with assisted resolution" with the
resolution diff saved. It is never silently reported as a clean merge.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from mergeset.base import (
    Change,
    ChangeId,
    ChangeSet,
    Evaluation,
    MergeOutcome,
    Stage,
    ValidationOutcome,
    Verdict,
    set_key,
)
from mergeset.gitops import git, merged_worktree
from mergeset.stacks import Dependencies, tips
from mergeset.validation import pytest_validation

#: A resolver: ``(worktree, conflicting_files) -> (resolved?, diff)``.
Resolver = Callable[[str, Sequence[str]], Tuple[bool, str]]


def merge_order(subset: ChangeSet, changes: Dict[ChangeId, Change]) -> Sequence[ChangeId]:
    """A deterministic merge order for a change set.

    Order should not matter when merges are clean; when it does, the run is
    recorded with the order that was used so the result stays reproducible.
    Stacked changes are merged parent-first; otherwise smallest-first, which
    surfaces the cheap conflicts early.

    >>> merge_order(frozenset({'b', 'a'}), {})
    ['a', 'b']
    """
    def sort_key(cid: ChangeId):
        change = changes.get(cid)
        meta = change.meta if change else {}
        stacked_on = meta.get("stacked_on")
        return (1 if stacked_on else 0, meta.get("additions") or 0, cid)

    return sorted(subset, key=sort_key)


def git_oracle(
    repo: str,
    base: str,
    changes: Iterable[Change],
    *,
    validate: Optional[Callable[[str], ValidationOutcome]] = None,
    resolver: Optional[Resolver] = None,
    depends_on: Optional[Dependencies] = None,
    reuse_worktree: Optional[str] = None,
    worktree_root: Optional[str] = None,
    keep_worktrees: bool = False,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> Callable[[ChangeSet], Evaluation]:
    """Build the evaluator: merge the set onto ``base``, then validate the tree.

    Args:
        repo: Path to the git repository (worktrees are created off it).
        base: The commit everything is merged onto.
        changes: The changes in play; only their ids are passed around later.
        validate: ``worktree -> ValidationOutcome``. Defaults to a fail-fast
            pytest run; see :mod:`mergeset.validation` for the alternatives.
        resolver: Optional AI-assisted conflict resolver. When given, a textual
            conflict is offered to it once; a success is recorded with
            ``merge.assisted = True`` and the diff kept.
        depends_on: ``child -> parent`` for stacked changes. Only the *tips* of
            a set are merged, because merging a tip already brings its
            ancestors; merging them explicitly is wasted work and perturbs the
            merge order for no reason.
        reuse_worktree: An existing worktree to check every candidate merge out
            into, instead of a fresh one per evaluation. This is what makes an
            expensive per-tree setup (dependency install, build cache)
            amortizable across the whole run.
        worktree_root: Where throwaway worktrees go. Default: a temp dir.
        keep_worktrees: Keep them for inspection (they add up fast).
        on_event: ``(event, payload)`` progress callback.

    Returns:
        ``evaluate(subset) -> Evaluation``. Wrap it in
        ``EvaluationLog.caching`` before handing it to the solver.
    """
    by_id = {c.id: c for c in changes}
    parents = dict(depends_on or {})
    validate = validate or pytest_validation()
    emit = on_event or (lambda name, payload: None)

    def evaluate(subset: ChangeSet) -> Evaluation:
        started = time.time()
        subset = frozenset(subset)
        if not subset:
            return Evaluation(subset, Verdict.PASS, note="empty set is good by fiat")
        to_merge = tips(subset, parents) if parents else subset
        order = merge_order(to_merge, by_id)
        heads = [(cid, by_id[cid].head) for cid in order]
        emit("merging", {"subset": set_key(subset), "order": list(order)})
        with merged_worktree(
            repo, base, heads, root=worktree_root, keep=keep_worktrees,
            reuse=reuse_worktree,
        ) as (worktree, outcome):
            if worktree is None and resolver is not None and outcome.conflicting_files:
                worktree, outcome = _try_assisted(
                    repo, base, heads, outcome, resolver, worktree_root, emit
                )
            if worktree is None:
                return Evaluation(
                    subset=subset,
                    verdict=Verdict.FAIL,
                    stage=Stage.MERGE,
                    merge=outcome,
                    duration=time.time() - started,
                    note="textual merge conflict",
                )
            emit("validating", {"subset": set_key(subset)})
            validation = validate(worktree)
        return Evaluation(
            subset=subset,
            verdict=Verdict.PASS if validation.ok else Verdict.FAIL,
            stage=Stage.VALIDATE,
            merge=outcome,
            validation=validation,
            duration=time.time() - started,
            note="assisted resolution" if outcome.assisted else "",
        )

    return evaluate


def _try_assisted(repo, base, heads, outcome, resolver, worktree_root, emit):
    """Second attempt at a conflicted merge, this time offering it to ``resolver``."""
    emit("assisted_merge", {"files": list(outcome.conflicting_files)})
    keeper = merged_worktree(repo, base, heads, root=worktree_root, keep=True)
    worktree, retry = keeper.__enter__()
    try:
        if worktree is not None:  # merged cleanly this time; nothing to resolve
            return worktree, retry
        # Re-run the merge without aborting so the resolver sees the conflict.
        path = _worktree_with_conflict(repo, base, heads, worktree_root)
        if path is None:
            return None, outcome
        resolved, diff = resolver(path, outcome.conflicting_files)
        if not resolved:
            return None, outcome
        return path, MergeOutcome(
            ok=True,
            conflicting_files=outcome.conflicting_files,
            assisted=True,
            assist_diff=diff,
            order=outcome.order,
            detail="conflict resolved by assisted merge; review the diff",
        )
    finally:
        keeper.__exit__(None, None, None)


def _worktree_with_conflict(repo, base, heads, worktree_root) -> Optional[str]:
    """Materialize the merge and *leave it conflicted* for a resolver to fix."""
    import tempfile

    root = worktree_root or tempfile.mkdtemp(prefix="mergeset-")
    os.makedirs(root, exist_ok=True)
    path = tempfile.mkdtemp(prefix="assist-", dir=root)
    os.rmdir(path)
    if not git(repo, "worktree", "add", "--detach", path, base).ok:
        return None
    for _, head in heads:
        res = git(
            path, "-c", "user.email=mergeset@localhost", "-c", "user.name=mergeset",
            "merge", "--no-edit", "--no-ff", head,
        )
        if not res.ok:
            return path  # left conflicted on purpose
    return path


def claude_code_resolver(
    *, timeout: float = 300.0, command: str = "claude"
) -> Resolver:
    """Resolve conflicts with a Claude Code subagent, under a strict policy.

    The policy is in the prompt and is deliberately narrow: mechanical conflicts
    only (import blocks, changelog entries, adjacent independent edits, lockfile
    regeneration), and an explicit refusal whenever the resolution requires
    guessing intent. Anything it does resolve is flagged and its diff kept.
    """
    import subprocess

    policy = (
        "You are resolving a git merge conflict inside a throwaway worktree.\n"
        "POLICY — follow exactly:\n"
        "1. Resolve ONLY mechanical conflicts: both sides added imports, both "
        "appended to a list/changelog, edits to adjacent but independent lines, "
        "regenerable lockfiles.\n"
        "2. NEVER guess intent. If resolving requires deciding which behaviour is "
        "correct, STOP and print exactly: UNRESOLVED\n"
        "3. Do not modify anything that is not conflicted.\n"
        "4. When done, `git add` the resolved files and `git commit --no-edit`, "
        "then print exactly: RESOLVED\n"
        "Conflicted files: {files}\n"
    )

    def resolve(worktree: str, files: Sequence[str]) -> Tuple[bool, str]:
        proc = subprocess.run(
            [command, "-p", policy.format(files=", ".join(files))],
            cwd=worktree, capture_output=True, text=True, timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if "UNRESOLVED" in output or "RESOLVED" not in output:
            return False, output[-2000:]
        unmerged = git(worktree, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        if unmerged:
            return False, f"resolver claimed success but left conflicts: {unmerged}"
        diff = git(worktree, "show", "--stat", "--patch", "HEAD").stdout
        return True, diff[:20000]

    return resolve
