"""An assisted resolution is made once, at the screen, and reused (#30).

Since #28 a deeper tier can merge what the resolver merged for the screen; it
did so by asking the resolver again, so paid resolver calls multiplied by the
number of tiers and a deep tier could validate a different resolved tree. These
tests use a scripted resolver (no AI) and count its calls.
"""

import os

import pytest

from mergeset.base import Change, MergeOutcome, Verdict
from mergeset.gitops import git, is_ancestor, resolve
from mergeset.oracle import git_oracle
from mergeset.tiers import Tier, analyze_tiered
from mergeset.validation import command_validation
from conftest import py_command

_PASS = "raise SystemExit(0)\n"
# Passes the base; on a tree holding the resolution, also wants feat-d's file.
_NEEDS_D = (
    "import os, sys\n"
    "resolved = 'CCC' in open('shared.txt').read() and 'AAA' in open('shared.txt').read()\n"
    "sys.exit(1 if resolved and not os.path.exists('new-d.txt') else 0)\n"
)


def _scripted_resolver(calls):
    """Resolve the shared.txt conflict by keeping both edits, and commit."""

    def resolver(worktree, files):
        calls.append(sorted(files))
        with open(os.path.join(worktree, "shared.txt"), "w") as f:
            f.write("line one\nAAA\nCCC\nline three\n")
        git(worktree, "add", "-A")
        committed = git(
            worktree,
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=T",
            "commit",
            "--no-edit",
        )
        return committed.ok, "kept both edits"

    return resolver


def _changes(names):
    return [Change(id=n, head=n, base="main") for n in names]


def _tiered(repo, tmp_path, names, deep_code=_PASS, **kwargs):
    ok = command_validation(py_command(tmp_path, "pass", _PASS))
    deep = command_validation(py_command(tmp_path, "deep", deep_code))
    return analyze_tiered(
        repo,
        _changes(names),
        base="main",
        tiers=[Tier("screen", ok), Tier("deep", deep)],
        pairwise_preoracle=False,
        decompose=False,
        use_ci_status=False,
        **kwargs,
    )


def test_the_resolver_is_asked_once_not_once_per_tier(repo, tmp_path):
    calls = []
    result = _tiered(
        repo, tmp_path, ["feat-a", "feat-c"], resolver=_scripted_resolver(calls)
    )
    pair = frozenset({"feat-a", "feat-c"})
    assert result.maximal_sets == [pair]
    assert result.verified_tier(pair) == "deep"
    assert len(calls) == 1, calls
    screen = result.logs["screen"].exact(pair).merge
    deep = result.logs["deep"].exact(pair).merge
    assert screen.assisted and deep.assisted
    assert screen.resolved_commit and deep.resolved_commit == screen.resolved_commit


def test_the_resolution_survives_the_log(repo, tmp_path):
    calls = []
    result = _tiered(
        repo, tmp_path, ["feat-a", "feat-c"], resolver=_scripted_resolver(calls)
    )
    pair = frozenset({"feat-a", "feat-c"})
    path = result.logs["screen"].store.path
    rows = [line for line in open(path) if '"merge_resolved_commit": "' in line]
    assert rows, "the resolved commit is written beside `merge`"
    from mergeset.log import EvaluationLog

    reread = EvaluationLog(path).exact(pair)
    assert reread.merge.resolved_commit == result.logs["screen"].exact(
        pair
    ).merge.resolved_commit


def test_every_head_is_merged_on_the_resolver_path(repo, tmp_path):
    """The resolver used to get the tree at the *first* conflict, and the heads
    after it were never merged -- while the row claimed the whole set."""
    calls = []
    result = _tiered(
        repo,
        tmp_path,
        ["feat-a", "feat-c", "feat-d"],
        deep_code=_NEEDS_D,
        resolver=_scripted_resolver(calls),
    )
    triple = frozenset({"feat-a", "feat-c", "feat-d"})
    row = result.logs["screen"].exact(triple)
    assert row is not None and row.verdict is Verdict.PASS
    for head in ("feat-a", "feat-c", "feat-d"):
        assert is_ancestor(repo, resolve(repo, head), row.merge.resolved_commit)
    assert result.maximal_sets == [triple]
    assert result.verified_tier(triple) == "deep"


def test_assisted_worktrees_are_removed(repo, tmp_path):
    _tiered(repo, tmp_path, ["feat-a", "feat-c"], resolver=_scripted_resolver([]))
    listed = git(repo, "worktree", "list").stdout.strip().splitlines()
    assert len(listed) == 1, listed


def _deep_oracle(repo, tmp_path, recorded):
    return git_oracle(
        repo,
        resolve(repo, "main"),
        [Change(id=n, head=resolve(repo, n), base="main") for n in ("feat-a", "feat-c")],
        validate=command_validation(py_command(tmp_path, "pass", _PASS)),
        resolution=lambda subset: recorded,
    )


def test_a_recorded_resolution_that_does_not_hold_every_head_is_refused(
    repo, tmp_path
):
    stale = MergeOutcome(ok=True, assisted=True, resolved_commit=resolve(repo, "feat-a"))
    row = _deep_oracle(repo, tmp_path, stale)(frozenset({"feat-a", "feat-c"}))
    assert row.verdict is Verdict.ERROR
    assert "no longer applies" in row.note


def test_a_missing_resolution_is_refused_not_guessed(repo, tmp_path):
    row = _deep_oracle(repo, tmp_path, None)(frozenset({"feat-a", "feat-c"}))
    assert row.verdict is Verdict.ERROR
    assert "no assisted resolution" in row.note
    gone = MergeOutcome(ok=True, assisted=True, resolved_commit="0" * 40)
    row = _deep_oracle(repo, tmp_path, gone)(frozenset({"feat-a", "feat-c"}))
    assert row.verdict is Verdict.ERROR and "no longer exists" in row.note


def test_resolver_and_resolution_are_exclusive(repo):
    with pytest.raises(ValueError, match="not both"):
        git_oracle(
            repo,
            "main",
            [],
            resolver=_scripted_resolver([]),
            resolution=lambda subset: None,
        )
