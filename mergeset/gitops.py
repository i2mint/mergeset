"""Git primitives: the cheap pre-oracles and the isolated merge.

Two very different costs live here, and keeping them apart is the point:

- **Cheap** (milliseconds, no working tree): ``git merge-tree --write-tree``
  answers "do these two changes conflict textually?" and ``git diff --name-only``
  answers "which files does this change touch?". Everything these two can decide
  must never reach the expensive oracle.
- **Expensive** (seconds to minutes): actually materializing a merged tree in a
  throwaway worktree so a test suite can run on it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from mergeset.base import CapabilityError, ChangeId, MergeOutcome

#: ``git merge-tree --write-tree`` needs this; it is also when ``--merge-base`` landed.
MIN_GIT_VERSION = (2, 38)


@dataclass(frozen=True)
class GitResult:
    """Raw result of one git invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """True iff git exited 0."""
        return self.returncode == 0


def git(
    repo: str, *args: str, check: bool = False, timeout: Optional[float] = None
) -> GitResult:
    """Run ``git -C repo *args`` and capture its output.

    >>> git('.', 'rev-parse', '--git-dir').ok in (True, False)
    True
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    result = GitResult(proc.returncode, proc.stdout, proc.stderr)
    if check and not result.ok:
        raise CapabilityError(
            f"git {' '.join(args)} failed in {repo}:\n{result.stderr.strip()}"
        )
    return result


def git_version() -> Tuple[int, ...]:
    """The installed git version as a tuple, e.g. ``(2, 50, 1)``."""
    out = subprocess.run(
        ["git", "--version"], capture_output=True, text=True
    ).stdout.strip()
    digits = out.split()[2].split(".")
    version: List[int] = []
    for part in digits:
        if part.isdigit():
            version.append(int(part))
        else:
            break
    return tuple(version)


def check_git_capability() -> None:
    """Raise a fixable error if git is missing or too old for ``merge-tree``."""
    if shutil.which("git") is None:
        raise CapabilityError(
            "git is not on PATH. Install it (https://git-scm.com/downloads) "
            "or add it to PATH, then re-run."
        )
    version = git_version()
    if version < MIN_GIT_VERSION:
        raise CapabilityError(
            f"git {'.'.join(map(str, version))} is too old: "
            f"mergeset needs >= {'.'.join(map(str, MIN_GIT_VERSION))} for "
            "`git merge-tree --write-tree` (the pre-oracle that finds textual "
            "conflicts without touching a worktree). Upgrade git, or pass "
            "pairwise_preoracle=False to skip it."
        )


def resolve(repo: str, rev: str) -> str:
    """Full sha of ``rev``.

    Raises:
        CapabilityError: if the revision cannot be resolved in ``repo``.
    """
    return git(
        repo, "rev-parse", "--verify", f"{rev}^{{commit}}", check=True
    ).stdout.strip()


def merge_base(repo: str, a: str, b: str) -> str:
    """Best common ancestor of ``a`` and ``b``."""
    return git(repo, "merge-base", a, b, check=True).stdout.strip()


def changed_files(repo: str, base: str, head: str) -> List[str]:
    """Files a change touches, as ``git diff --name-only base...head``.

    The three-dot form is deliberate: it compares against the merge base, so a
    change is measured by what *it* did, not by what happened on base meanwhile.
    """
    result = git(repo, "diff", "--name-only", f"{base}...{head}")
    if not result.ok:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def textual_conflict(
    repo: str, base: str, head_a: str, head_b: str
) -> Optional[List[str]]:
    """Conflicting files if merging both heads onto ``base`` clashes textually.

    **This chains through ``base`` on purpose.** Plain ``git merge-tree A B``
    merges using ``merge-base(A, B)``, which is *not* ``base`` whenever the two
    branches were cut at different times — and then it reports base's own
    commits as conflicts. On a real 15-PR set that mistake produced 13
    "conflicting" pairs where only 2 were real (measured by TEST on
    trial-repo). So we merge A onto base first, in the object database, and ask
    whether B then conflicts with *that*.

    Returns:
        ``None`` when the merge is clean, otherwise the list of conflicted paths
        (possibly empty if git reported a conflict it could not attribute).
    """
    conflict = merge_sequence(repo, base, [("a", head_a), ("b", head_b)])
    return None if conflict.ok else list(conflict.conflicting_files)


@dataclass(frozen=True)
class SequenceMerge:
    """Result of merging changes onto a base entirely in the object database."""

    ok: bool
    #: Commit holding base + every merged head, when the whole sequence was clean.
    commit: Optional[str] = None
    conflicting_files: Sequence[str] = ()
    #: The changes merged so far; the last one is the one that conflicted.
    order: Sequence[ChangeId] = ()
    detail: str = ""


def merge_sequence(
    repo: str, base: str, heads: Sequence[Tuple[ChangeId, str]]
) -> SequenceMerge:
    """Merge every head onto ``base``, one at a time, without any worktree.

    The mechanic, which is the cheap heart of the whole tool::

        acc = base
        for each head:
            tree = git merge-tree --write-tree acc head   # conflict -> non-zero
            acc  = git commit-tree tree -p acc -p head

    ``n`` ``merge-tree`` calls of a few milliseconds each, no checkout, no
    working tree, and — when it comes out clean — a real commit that a worktree
    can be checked out from only if we actually intend to run tests on it.

    Every merge is measured against the accumulated result rather than pairwise,
    which is what keeps a stale branch from manufacturing false conflicts.
    """
    acc = resolve(repo, base)
    merged: List[ChangeId] = []
    for change_id, head in heads:
        merged.append(change_id)
        head_sha = resolve(repo, head)
        result = git(repo, "merge-tree", "--write-tree", acc, head_sha)
        if not result.ok:
            return SequenceMerge(
                ok=False,
                conflicting_files=_parse_merge_tree_conflicts(result.stdout),
                order=merged,
                detail=(result.stderr or result.stdout).strip()[-2000:],
            )
        tree = result.stdout.splitlines()[0].strip()
        commit = git(
            repo,
            "commit-tree",
            tree,
            "-p",
            acc,
            "-p",
            head_sha,
            "-m",
            f"mergeset: merge {change_id}",
            check=True,
        )
        acc = commit.stdout.strip()
    return SequenceMerge(ok=True, commit=acc, order=merged)


def _parse_merge_tree_conflicts(stdout: str) -> List[str]:
    """Pull the conflicted paths out of ``merge-tree --write-tree`` output.

    The format is: tree oid, blank line, ``<mode> <object> <stage>\\t<path>``
    lines, blank line, informational messages.

    >>> _parse_merge_tree_conflicts(
    ...     'abc123\\n\\n100644 aaa 1\\tfoo.py\\n100644 bbb 2\\tfoo.py\\n\\nAuto-merging foo.py\\n'
    ... )
    ['foo.py']
    """
    lines = stdout.splitlines()
    paths: List[str] = []
    for line in lines[1:]:
        if not line.strip():
            if paths:
                break
            continue
        if "\t" in line:
            paths.append(line.split("\t", 1)[1])
    seen = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def pairwise_textual_conflicts(
    repo: str, base: str, heads: dict
) -> Iterator[Tuple[ChangeId, ChangeId, List[str]]]:
    """Yield ``(id_a, id_b, files)`` for every pair that conflicts textually.

    ``heads`` maps change id -> commit-ish. This is the pre-oracle that buys the
    most: every pair it finds is a size-2 conflict known before any test runs.
    Each pair is merged *onto base*, never against each other — see
    :func:`textual_conflict` for why that distinction is not cosmetic.
    """
    ids = sorted(heads)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            files = textual_conflict(repo, base, heads[a], heads[b])
            if files is not None:
                yield a, b, files


def singleton_textual_conflicts(
    repo: str, base: str, heads: dict
) -> Iterator[Tuple[ChangeId, List[str]]]:
    """Yield ``(id, files)`` for every change that will not even merge onto base.

    The cheapest check there is, and on real PR sets it fires more than you would
    expect: a PR opened against a base branch that has since moved on is green on
    GitHub and still unmergeable onto the base you actually care about.
    """
    for change_id in sorted(heads):
        result = merge_sequence(repo, base, [(change_id, heads[change_id])])
        if not result.ok:
            yield change_id, list(result.conflicting_files)


@contextmanager
def merged_worktree(
    repo: str,
    base: str,
    heads: Sequence[Tuple[ChangeId, str]],
    *,
    root: Optional[str] = None,
    keep: bool = False,
    reuse: Optional[str] = None,
) -> Iterator[Tuple[Optional[str], MergeOutcome]]:
    """Materialize ``base`` plus every head in a worktree, ready for validation.

    The merge itself happens in the object database (:func:`merge_sequence`), so
    a conflicted set costs milliseconds and never touches the filesystem at all.
    Only a *clean* set gets checked out — which is the only case where anything
    wanted to run tests anyway.

    Yields ``(worktree_path, outcome)``. On a conflict the path is ``None`` and
    the outcome names the change that failed (``outcome.order[-1]``) and the
    conflicting files — that attribution is what lets the solver shrink straight
    to the suspects instead of halving blindly.

    Args:
        reuse: An existing worktree to check the merge commit out into, instead
            of creating a fresh one. This is the seam that makes expensive
            per-tree setup (``npm install``, a virtualenv, a build cache)
            survive across evaluations; see
            :func:`mergeset.validation.staged_validation`.
    """
    merged = merge_sequence(repo, base, heads)
    if not merged.ok:
        yield (
            None,
            MergeOutcome(
                ok=False,
                conflicting_files=merged.conflicting_files,
                order=merged.order,
                detail=merged.detail,
            ),
        )
        return
    outcome = MergeOutcome(ok=True, order=merged.order, detail=merged.commit or "")

    if reuse:
        reuse = os.path.abspath(os.path.expanduser(str(reuse)))
        if not os.path.isdir(reuse) or not git(reuse, "rev-parse", "--git-dir").ok:
            yield (
                None,
                MergeOutcome(
                    ok=False,
                    reason="error",
                    order=merged.order,
                    detail=(
                        f"reuse_worktree={reuse!r} is not a git worktree. Create one "
                        "with mergeset.gitops.persistent_worktree(repo, base, path), "
                        "and pass an absolute path (it must be a str, not True)."
                    ),
                ),
            )
            return
        checkout = git(reuse, "checkout", "--force", "--detach", merged.commit)
        if not checkout.ok:
            yield (
                None,
                MergeOutcome(
                    ok=False,
                    reason="error",
                    order=merged.order,
                    detail=f"could not check out into {reuse}: {checkout.stderr.strip()}",
                ),
            )
            return
        git(reuse, "clean", "-fd")
        yield reuse, outcome
        return

    root = root or tempfile.mkdtemp(prefix="mergeset-")
    os.makedirs(root, exist_ok=True)
    path = tempfile.mkdtemp(prefix="wt-", dir=root)
    os.rmdir(path)  # `git worktree add` wants to create it
    added = False
    try:
        add = git(repo, "worktree", "add", "--detach", path, merged.commit)
        if not add.ok:
            yield (
                None,
                MergeOutcome(
                    ok=False,
                    reason="error",
                    order=merged.order,
                    detail=f"could not create worktree: {add.stderr.strip()}",
                ),
            )
            return
        added = True
        yield path, outcome
    finally:
        if added and not keep:
            git(repo, "worktree", "remove", "--force", path)
            git(repo, "worktree", "prune")


def persistent_worktree(repo: str, base: str, path: str) -> str:
    """Create (once) a worktree meant to be reused across many evaluations.

    Reusing one tree is what makes an expensive setup step amortizable: install
    dependencies once, then check out each candidate merge into the same
    directory. Returns ``path``.
    """
    if not os.path.isdir(os.path.join(path, ".git")) and not os.path.exists(path):
        git(repo, "worktree", "add", "--detach", path, base, check=True)
    return path


def create_integration_branch(
    repo: str,
    name: str,
    base: str,
    heads: Sequence[Tuple[ChangeId, str]],
    *,
    force: bool = False,
) -> Tuple[bool, str]:
    """Create a local branch holding ``base`` + all heads, for manual testing.

    Only ever creates *new* local branches. Never touches an existing branch
    unless ``force`` is passed explicitly, and never pushes anything.

    Returns:
        ``(created, message)``.
    """
    exists = git(repo, "rev-parse", "--verify", f"refs/heads/{name}").ok
    if exists and not force:
        return False, f"branch {name} already exists; refusing to touch it"
    with merged_worktree(repo, base, heads) as (path, outcome):
        if path is None:
            return False, f"merge failed: {outcome.detail or 'conflict'}"
        sha = git(path, "rev-parse", "HEAD", check=True).stdout.strip()
    res = git(repo, "branch", "--force" if force else "--no-track", name, sha)
    if not res.ok:
        return False, res.stderr.strip()
    return True, sha
