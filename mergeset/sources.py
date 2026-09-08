"""Change sources: where the candidate changes come from.

A **source** is any callable returning an iterable of :class:`~mergeset.base.Change`.
Branches, pull requests and explicit commit lists are just different sources of
the same thing — a ``base..head`` range — which is why the rest of the package
never mentions the word "PR".

PR sources carry the extra metadata that only a forge knows (author, title, CI
status, base branch, draft flag, stack relationships); it rides along in
``Change.meta`` and is used for weighting and for the report, never by the
solver.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence

from mergeset.base import CapabilityError, Change
from mergeset.gitops import changed_files, git, resolve

#: Fields worth asking `gh` for; anything else is noise in the report.
PR_FIELDS = (
    "number,title,author,headRefName,baseRefName,isDraft,updatedAt,createdAt,"
    "state,mergeable,statusCheckRollup,url,additions,deletions,changedFiles"
)


def branch_changes(
    repo: str,
    branches: Iterable[str],
    *,
    base: str = "HEAD",
    prefix: str = "",
) -> Iterator[Change]:
    """Changes from local or remote branches.

    >>> list(branch_changes('.', []))
    []
    """
    for branch in branches:
        yield Change(
            id=(prefix + branch.rsplit("/", 1)[-1]),
            head=branch,
            base=base,
            source="branch",
            meta={"ref": branch},
        )


def local_branch_names(
    repo: str, *, pattern: Optional[str] = None, exclude: Sequence[str] = ()
) -> List[str]:
    """Local branch names, optionally filtered by a glob ``pattern``."""
    args = ["for-each-ref", "--format=%(refname:short)", "refs/heads/"]
    if pattern:
        args.append(f"refs/heads/{pattern}")
    names = git(repo, *args).stdout.split()
    return [n for n in names if n not in set(exclude)]


def commit_changes(
    repo: str, commits: Iterable[str], *, base: str = "HEAD"
) -> Iterator[Change]:
    """Changes from an explicit list of commit-ishes, one change per commit."""
    for commit in commits:
        sha = resolve(repo, commit)
        yield Change(
            id=sha[:8],
            head=sha,
            base=base,
            source="commit",
            meta={"subject": git(repo, "log", "-1", "--format=%s", sha).stdout.strip()},
        )


def check_gh_capability() -> None:
    """Raise a fixable error if the GitHub CLI is unusable."""
    if shutil.which("gh") is None:
        raise CapabilityError(
            "The GitHub CLI (`gh`) is not installed; it is how mergeset reads "
            "pull requests. Install it (https://cli.github.com/) and run "
            "`gh auth login`, or use branch/commit sources instead."
        )
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        raise CapabilityError(
            "`gh` is installed but not authenticated. Run `gh auth login`."
        )


def fetch_pull_requests(
    repo_spec: str,
    *,
    author: Optional[str] = None,
    state: str = "open",
    limit: int = 100,
    extra_args: Sequence[str] = (),
) -> List[dict]:
    """Raw ``gh pr list`` records for ``repo_spec`` (``owner/name``)."""
    check_gh_capability()
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo_spec,
        "--state",
        state,
        "--limit",
        str(limit),
        "--json",
        PR_FIELDS,
    ]
    if author:
        cmd += ["--author", author]
    cmd += list(extra_args)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CapabilityError(f"`gh pr list` failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "[]")


def pr_changes(
    repo: str,
    pull_requests: Iterable[dict],
    *,
    base: Optional[str] = None,
    ref_of: Optional[Callable[[dict], str]] = None,
) -> Iterator[Change]:
    """Turn ``gh pr list`` records into changes.

    Args:
        repo: Local clone the refs live in.
        pull_requests: Records as produced by :func:`fetch_pull_requests`.
        base: Override base for every change. Default: each PR's own base ref,
            which is what makes stacked PRs visible rather than silently wrong.
        ref_of: How to name a PR's head ref locally. Default ``origin/<headRef>``.
    """
    ref_of = ref_of or (lambda pr: f"origin/{pr['headRefName']}")
    for pr in pull_requests:
        checks = pr.get("statusCheckRollup") or []
        yield Change(
            id=f"pr{pr['number']}",
            head=ref_of(pr),
            base=base or f"origin/{pr.get('baseRefName', 'main')}",
            source="pr",
            meta={
                "number": pr.get("number"),
                "title": pr.get("title"),
                "author": (pr.get("author") or {}).get("login"),
                "url": pr.get("url"),
                "head_ref": pr.get("headRefName"),
                "base_ref": pr.get("baseRefName"),
                "draft": pr.get("isDraft"),
                "updated_at": pr.get("updatedAt"),
                "state": pr.get("state"),
                "mergeable": pr.get("mergeable"),
                "ci": _rollup_state(checks),
                "additions": pr.get("additions"),
                "deletions": pr.get("deletions"),
                "changed_files": pr.get("changedFiles"),
            },
        )


def _rollup_state(checks: Sequence[dict]) -> Optional[str]:
    """Reduce a ``statusCheckRollup`` to one word.

    >>> _rollup_state([{'conclusion': 'SUCCESS'}, {'conclusion': 'FAILURE'}])
    'failure'
    >>> _rollup_state([]) is None
    True
    """
    if not checks:
        return None
    states = {(c.get("conclusion") or c.get("state") or "").upper() for c in checks}
    if {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED"} & states:
        return "failure"
    if {"PENDING", "IN_PROGRESS", "QUEUED", ""} & states:
        return "pending"
    return "success"


def detect_stacks(changes: Sequence[Change]) -> Dict[str, str]:
    """Map change id -> the change id it is stacked on, for PR stacks.

    A PR whose base ref is another candidate's head ref is *stacked*: only
    prefixes of the chain make sense as a merge set, because the child contains
    the parent. Recorded so the report can say so and the solver can be told.

    >>> a = Change(id='pr1', head='origin/a', base='origin/main', source='pr',
    ...            meta={'head_ref': 'a', 'base_ref': 'main'})
    >>> b = Change(id='pr2', head='origin/b', base='origin/a', source='pr',
    ...            meta={'head_ref': 'b', 'base_ref': 'a'})
    >>> detect_stacks([a, b])
    {'pr2': 'pr1'}
    """
    by_head_ref = {
        c.meta.get("head_ref"): c.id for c in changes if c.meta.get("head_ref")
    }
    return {
        c.id: by_head_ref[c.meta["base_ref"]]
        for c in changes
        if c.meta.get("base_ref") in by_head_ref
        and by_head_ref[c.meta["base_ref"]] != c.id
    }


def size_weight(repo: str, change: Change) -> float:
    """Default weight: how much it costs to drop this change.

    Bigger changes are worth more (dropping a 900-line PR wastes more work than
    dropping a typo fix), so the weighted hitting set prefers to drop the small
    ones. ``log``-shaped so one huge branch does not dominate everything.

    Override with any ``Change -> float``; PR metadata (priority labels,
    author, age) is right there in ``change.meta`` for the taking.
    """
    from math import log1p

    added = change.meta.get("additions")
    deleted = change.meta.get("deletions")
    if added is None:
        stat = git(repo, "diff", "--shortstat", f"{change.base}...{change.head}").stdout
        numbers = [int(s) for s in stat.replace(",", " ").split() if s.isdigit()]
        size = sum(numbers[1:]) if len(numbers) > 1 else len(numbers)
    else:
        size = (added or 0) + (deleted or 0)
    return 1.0 + log1p(max(size, 0))
