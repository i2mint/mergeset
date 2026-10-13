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


def _tiered(repo, tmp_path, names, deep_code=_PASS, deep_name="deep", **kwargs):
    ok = command_validation(py_command(tmp_path, "pass", _PASS))
    deep = command_validation(py_command(tmp_path, deep_name, deep_code))
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


def _commit(worktree):
    return git(
        worktree,
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=T",
        "commit",
        "--no-edit",
        "--allow-empty",
    ).ok


def _screen_only(repo, tmp_path, names, resolver):
    from mergeset.analysis import analyze

    return analyze(
        repo,
        _changes(names),
        base="main",
        validate=command_validation(py_command(tmp_path, "pass", _PASS)),
        resolver=resolver,
        pairwise_preoracle=False,
        decompose=False,
        use_ci_status=False,
    )


def test_a_resolver_that_drops_earlier_heads_has_declined(repo, tmp_path):
    """Review of #38: taking one side wholesale passed the old check."""

    def theirs(worktree, files):
        git(worktree, "merge", "--abort")
        git(worktree, "reset", "--hard", "MERGE_HEAD")
        return True, "took theirs"

    analysis = _screen_only(repo, tmp_path, ["feat-a", "feat-b", "feat-c"], theirs)
    triple = frozenset({"feat-a", "feat-b", "feat-c"})
    row = analysis.log.exact(triple)
    assert row is None or row.verdict is not Verdict.PASS
    assert triple not in analysis.maximal_sets


def test_files_a_resolver_leaves_outside_its_commit_are_not_validated(repo, tmp_path):
    """The screen must validate the recorded commit, not a dirty tree (#38).

    Untracked and ignored leftovers (a regenerated lockfile, ``__pycache__``)
    are removed rather than declined: a resolver that ran the tests is not
    a resolver that failed.
    """

    def leaves_files(worktree, files):
        _scripted_resolver([])(worktree, files)
        with open(os.path.join(worktree, "stray.txt"), "w") as f:
            f.write("regenerated, never committed\n")
        return True, "kept both edits"

    from mergeset.analysis import analyze

    no_stray = "import os, sys\nsys.exit(1 if os.path.exists('stray.txt') else 0)\n"
    analysis = analyze(
        repo,
        _changes(["feat-a", "feat-c"]),
        base="main",
        validate=command_validation(py_command(tmp_path, "nostray", no_stray)),
        resolver=leaves_files,
        pairwise_preoracle=False,
        decompose=False,
        use_ci_status=False,
    )
    assert frozenset({"feat-a", "feat-c"}) in analysis.maximal_sets


def test_a_resolver_that_leaves_tracked_edits_uncommitted_has_declined(
    repo, tmp_path
):
    def uncommitted(worktree, files):
        _scripted_resolver([])(worktree, files)
        with open(os.path.join(worktree, "other.txt"), "a") as f:
            f.write("edited after the commit\n")
        return True, "kept both edits"

    analysis = _screen_only(repo, tmp_path, ["feat-a", "feat-c"], uncommitted)
    assert frozenset({"feat-a", "feat-c"}) not in analysis.maximal_sets


def test_a_resolver_that_keeps_a_heads_commit_but_not_its_work_has_declined(
    repo, tmp_path
):
    """``merge -s ours`` keeps feat-c as a parent and drops what it did."""
    from conftest import run

    run(repo, "checkout", "-q", "feat-c")
    with open(os.path.join(repo, "c_only.txt"), "w") as f:
        f.write("only feat-c has this\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "feat-c: more work")
    run(repo, "checkout", "-q", "main")

    def ours(worktree, files):
        git(worktree, "merge", "--abort")
        merged = git(
            worktree,
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=T",
            "merge",
            "--no-edit",
            "-s",
            "ours",
            "feat-c",
        )
        return merged.ok, "kept ours"

    analysis = _screen_only(repo, tmp_path, ["feat-a", "feat-c"], ours)
    assert frozenset({"feat-a", "feat-c"}) not in analysis.maximal_sets


def test_a_resolver_that_raises_has_declined_and_leaks_nothing(repo, tmp_path):
    """A timeout is a resolver giving up: a conflict, not an ERROR that would
    abort the whole search over one slow call."""

    def broken(worktree, files):
        raise TimeoutError("resolver timed out")

    row = git_oracle(
        repo,
        resolve(repo, "main"),
        _changes(["feat-a", "feat-c"]),
        validate=command_validation(py_command(tmp_path, "pass", _PASS)),
        resolver=broken,
    )(frozenset({"feat-a", "feat-c"}))
    assert row.verdict is Verdict.FAIL and row.note == "textual merge conflict"
    assert len(git(repo, "worktree", "list").stdout.strip().splitlines()) == 1


def test_only_the_resolution_namespace_is_written(repo, tmp_path):
    def refs():
        listed = git(repo, "for-each-ref", "--format=%(refname)").stdout.split()
        return set(listed)

    before = refs()
    _tiered(repo, tmp_path, ["feat-a", "feat-c"], resolver=_scripted_resolver([]))
    added = refs() - before
    assert added and all(r.startswith("refs/mergeset/resolved/") for r in added)


def test_a_resolution_survives_garbage_collection(repo, tmp_path):
    calls = []
    _tiered(repo, tmp_path, ["feat-a", "feat-c"], resolver=_scripted_resolver(calls))
    git(repo, "-c", "gc.reflogExpire=now", "reflog", "expire", "--all")
    git(repo, "gc", "--prune=now", "--quiet")
    # The screen answers from its log; the deep tier, edited (another command,
    # so another fingerprint), must re-run and find the screen's resolution
    # still there. No resolver this time.
    again = _tiered(repo, tmp_path, ["feat-a", "feat-c"], deep_name="deep-v2")
    assert again.logs["deep"].other_validator, "the deep tier really re-ran"
    pair = frozenset({"feat-a", "feat-c"})
    assert again.logs["deep"].exact(pair).verdict is Verdict.PASS
    assert again.verified_tier(pair) == "deep"
    assert len(calls) == 1
