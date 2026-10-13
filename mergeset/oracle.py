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
from dataclasses import dataclass, replace
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
from mergeset.gitops import git, is_ancestor, merged_worktree, resolve
from mergeset.stacks import Dependencies, tips
from mergeset.validation import pytest_validation

#: A resolver: ``(worktree, conflicting_files) -> (resolved?, diff)``.
Resolver = Callable[[str, Sequence[str]], Tuple[bool, str]]


def merge_order(
    subset: ChangeSet, changes: Dict[ChangeId, Change]
) -> Sequence[ChangeId]:
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
    resolution: Optional[Callable[[ChangeSet], Optional[MergeOutcome]]] = None,
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
            conflict is offered to it; a success is recorded with
            ``merge.assisted = True``, the diff kept, and the resolved merge
            commit kept as ``merge.resolved_commit``.
        resolution: ``subset -> MergeOutcome`` of an earlier assisted
            resolution of that set, or ``None`` -- the alternative to
            ``resolver`` for a deeper tier (i2mint/mergeset#30). A conflicting
            set is then not resolved again: the recorded commit is checked out,
            once it is shown to hold the base and every head, so every tier
            validates the very tree the first one did and the resolver is paid
            once. A conflict with no usable recorded resolution is an
            ``ERROR``, never a guess.
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
    if resolver is not None and resolution is not None:
        raise ValueError(
            "Pass `resolver` (resolve conflicts now) or `resolution` (reuse "
            "resolutions recorded earlier), not both."
        )
    by_id = {c.id: c for c in changes}
    parents = dict(depends_on or {})
    validate = validate or pytest_validation()
    emit = on_event or (lambda name, payload: None)

    def evaluate(subset: ChangeSet) -> Evaluation:
        started = time.time()
        subset = frozenset(subset)
        # The empty set is not "trivially good": it is the base, and running
        # the validator on it is how a broken base or a wrong test command
        # becomes a refusal instead of n confident failures.
        order: Sequence[ChangeId] = ()
        if subset:
            to_merge = tips(subset, parents) if parents else subset
            order = merge_order(to_merge, by_id)
        heads = [(cid, by_id[cid].head) for cid in order]
        emit("merging", {"subset": set_key(subset), "order": list(order)})
        with merged_worktree(
            repo,
            base,
            heads,
            root=worktree_root,
            keep=keep_worktrees,
            reuse=reuse_worktree,
        ) as (worktree, outcome):
            assisted_tree = None
            if worktree is None and outcome.conflicting_files:
                if resolver is not None:
                    worktree, outcome = _try_assisted(
                        repo, base, heads, outcome, resolver, worktree_root, emit
                    )
                elif resolution is not None:
                    worktree, outcome = _reuse_resolution(
                        repo,
                        base,
                        heads,
                        outcome,
                        resolution(subset),
                        worktree_root=worktree_root,
                        reuse=reuse_worktree,
                    )
                # Ours to remove: `merged_worktree` only cleans up its own.
                if worktree is not None and worktree != reuse_worktree:
                    assisted_tree = worktree
            if worktree is None:
                failed = outcome.reason == "conflict"
                return Evaluation(
                    subset=subset,
                    verdict=Verdict.FAIL if failed else Verdict.ERROR,
                    stage=Stage.MERGE,
                    merge=outcome,
                    duration=time.time() - started,
                    note=(
                        "textual merge conflict"
                        if failed
                        else f"could not evaluate: {outcome.detail}"
                    ),
                )
            emit("validating", {"subset": set_key(subset)})
            try:
                validation = validate(worktree)
            finally:
                if assisted_tree is not None and not keep_worktrees:
                    _remove_worktree(repo, assisted_tree)
        return Evaluation(
            subset=subset,
            verdict=Verdict.PASS if validation.ok else Verdict.FAIL,
            stage=Stage.VALIDATE,
            merge=outcome,
            validation=validation,
            duration=time.time() - started,
            note=(
                "assisted resolution"
                if outcome.assisted
                else "base alone"
                if not subset
                else ""
            ),
        )

    return evaluate


def _try_assisted(repo, base, heads, outcome, resolver, worktree_root, emit):
    """Second attempt at a conflicted merge, offering each conflict to ``resolver``.

    Every head is merged, in order, and each one that conflicts is offered to
    the resolver in turn. An earlier version stopped at the first conflict and
    handed that half-merged tree to the resolver: the heads after it were never
    merged, yet the row claimed the whole set. The resolved merge commit is
    kept, so a deeper tier can validate the same tree (#30).
    """
    emit("assisted_merge", {"files": list(outcome.conflicting_files)})
    path = _new_worktree(repo, base, worktree_root)
    if path is None:
        return None, outcome
    diffs = []
    for _, head in heads:
        if _merge_into(path, head):
            continue
        conflicted = git(path, "diff", "--name-only", "--diff-filter=U").stdout.split()
        resolved, diff = resolver(path, conflicted or list(outcome.conflicting_files))
        unmerged = git(path, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        if not resolved or unmerged or not is_ancestor(path, head, "HEAD"):
            _remove_worktree(repo, path)
            return None, outcome
        diffs.append(diff)
    return path, MergeOutcome(
        ok=True,
        conflicting_files=outcome.conflicting_files,
        assisted=True,
        assist_diff="\n".join(diffs),
        order=outcome.order,
        detail="conflict resolved by assisted merge; review the diff",
        resolved_commit=resolve(path, "HEAD"),
    )


def _reuse_resolution(repo, base, heads, outcome, recorded, *, worktree_root, reuse):
    """Check out a recorded assisted resolution, once it is shown to still apply.

    It applies when the commit still exists and holds the base and every head
    being merged now: then it is the merge of exactly this set, conflicts
    resolved the way the first tier's resolver resolved them. Anything else is
    refused as an ``error`` -- a set that was never validated has told us
    nothing, and resolving it again would validate a different tree.
    """
    sha = recorded.resolved_commit if recorded is not None else None

    def refuse(why: str):
        return None, MergeOutcome(
            ok=False,
            reason="error",
            conflicting_files=outcome.conflicting_files,
            order=outcome.order,
            detail=f"conflict, and {why}",
        )

    if not sha:
        return refuse(
            "no assisted resolution of it was recorded to reuse (rows written "
            "before resolutions were kept record none; re-run the first tier "
            "with a fresh log)"
        )
    exists = git(repo, "cat-file", "-e", f"{sha}^{{commit}}").ok
    if not exists:
        return refuse(f"its recorded resolution {sha[:8]} no longer exists")
    missing = [
        rev for rev in [base, *(h for _, h in heads)] if not is_ancestor(repo, rev, sha)
    ]
    if missing:
        return refuse(
            f"its recorded resolution {sha[:8]} no longer applies: it does not "
            f"hold {', '.join(m[:8] for m in missing)}"
        )
    if reuse:
        if not git(reuse, "checkout", "--force", "--detach", sha).ok:
            return refuse(f"{sha[:8]} could not be checked out into {reuse}")
        git(reuse, "clean", "-fd")
        path = reuse
    else:
        path = _new_worktree(repo, sha, worktree_root)
        if path is None:
            return refuse(f"no worktree could be created at {sha[:8]}")
    return path, replace(
        recorded,
        order=outcome.order,
        detail=f"reused the assisted resolution {sha[:8]} recorded earlier",
    )


def _new_worktree(repo, commit, worktree_root) -> Optional[str]:
    """A fresh detached worktree at ``commit``, under ``worktree_root``."""
    import tempfile

    root = worktree_root or tempfile.mkdtemp(prefix="mergeset-")
    os.makedirs(root, exist_ok=True)
    path = tempfile.mkdtemp(prefix="assist-", dir=root)
    os.rmdir(path)
    if not git(repo, "worktree", "add", "--detach", path, commit).ok:
        return None
    return path


def _merge_into(path, head) -> bool:
    """Merge ``head`` into the worktree at ``path``; False leaves it conflicted."""
    return git(
        path,
        "-c",
        "user.email=mergeset@localhost",
        "-c",
        "user.name=mergeset",
        "merge",
        "--no-edit",
        "--no-ff",
        head,
    ).ok


def _remove_worktree(repo, path) -> None:
    git(repo, "worktree", "remove", "--force", path)
    git(repo, "worktree", "prune")


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
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if "UNRESOLVED" in output or "RESOLVED" not in output:
            return False, output[-2000:]
        unmerged = git(
            worktree, "diff", "--name-only", "--diff-filter=U"
        ).stdout.strip()
        if unmerged:
            return False, f"resolver claimed success but left conflicts: {unmerged}"
        diff = git(worktree, "show", "--stat", "--patch", "HEAD").stdout
        return True, diff[:20000]

    return resolve
