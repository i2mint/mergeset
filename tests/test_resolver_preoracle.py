"""A resolver is offered the conflicts the pre-oracle would exclude (#44).

With the `git merge-tree` pre-oracle on (the CLI default), every textual
conflict used to be seeded as a known failure before any evaluation, so a
resolver was never offered one and `--resolver claude` did nothing by default.
"""

from mergeset.analysis import analyze
from mergeset.base import Change
from mergeset.log import EvaluationLog
from mergeset.report import _analysis_jdict, markdown_report
from mergeset.validation import merge_only_validation

from test_resolution import _scripted_resolver


def _analyze(repo, tmp_path, names, **kwargs):
    return analyze(
        repo,
        [Change(id=n, head=n, base="main") for n in names],
        base="main",
        use_ci_status=False,
        log=EvaluationLog(str(tmp_path / "eval.jsonl")),
        **{"validate": merge_only_validation(), **kwargs},
    )


def test_the_preoracle_does_not_exclude_what_the_resolver_is_for(repo, tmp_path):
    calls = []
    analysis = _analyze(
        repo, tmp_path, ["feat-a", "feat-c"], resolver=_scripted_resolver(calls)
    )
    assert analysis.maximal_sets == [frozenset({"feat-a", "feat-c"})]
    assert calls, "the resolver was never offered the conflict"
    assert not analysis.textual_conflicts
    assert any("pre-oracle was skipped" in n for n in analysis.notes)


def test_without_a_resolver_the_preoracle_still_excludes(repo, tmp_path):
    analysis = _analyze(repo, tmp_path, ["feat-a", "feat-c"])
    assert [(a, b) for a, b, _ in analysis.textual_conflicts] == [
        ("feat-a", "feat-c")
    ]
    assert not any("pre-oracle was skipped" in n for n in analysis.notes)


def test_a_declined_conflict_is_reported_as_unmerged_not_as_validation(repo, tmp_path):
    calls = []

    def declines(worktree, files):
        calls.append(sorted(files))
        return False, "no"

    analysis = _analyze(repo, tmp_path, ["feat-a", "feat-c"], resolver=declines)
    assert calls
    pair = frozenset({"feat-a", "feat-c"})
    assert analysis.conflicts == [pair]
    report = markdown_report(analysis)
    assert "**Did not merge**" in report
    assert "shared.txt" in report.split("**Did not merge**")[1]
    assert "Conflicts found by validation" not in report
    [edge] = _analysis_jdict(analysis)["edges"]
    assert edge["kind"] == "textual" and edge["files"] == ["shared.txt"]


def test_an_explicit_preoracle_still_excludes_with_a_resolver(repo, tmp_path):
    calls = []
    analysis = _analyze(
        repo,
        tmp_path,
        ["feat-a", "feat-c"],
        resolver=_scripted_resolver(calls),
        pairwise_preoracle=True,
    )
    assert not calls
    assert len(analysis.maximal_sets) == 2


def test_without_a_resolver_did_not_merge_does_not_blame_one(repo, tmp_path):
    analysis = _analyze(
        repo, tmp_path, ["feat-a", "feat-c"], pairwise_preoracle=False
    )
    report = markdown_report(analysis)
    assert "**Did not merge** (found by merging):" in report
    assert "declined" not in report


def test_a_resolved_set_that_fails_validation_is_not_a_clean_merge(repo, tmp_path):
    from conftest import py_command
    from mergeset.validation import command_validation
    from test_resolution import _NEEDS_D

    calls = []
    analysis = _analyze(
        repo,
        tmp_path,
        ["feat-a", "feat-c"],
        resolver=_scripted_resolver(calls),
        validate=command_validation(py_command(tmp_path, "needs-d", _NEEDS_D)),
    )
    assert analysis.conflicts == [frozenset({"feat-a", "feat-c"})]
    report = markdown_report(analysis)
    assert "Merged only with an assisted resolution" in report
    assert "merged cleanly" not in report
    [edge] = _analysis_jdict(analysis)["edges"]
    assert edge["kind"] == "assisted"


def test_an_earlier_runs_decline_is_not_blamed_on_this_run(repo, tmp_path):
    def declines(worktree, files):
        return False, "no"

    _analyze(repo, tmp_path, ["feat-a", "feat-c"], resolver=declines)
    later = _analyze(repo, tmp_path, ["feat-a", "feat-c"], pairwise_preoracle=False)
    report = markdown_report(later)
    assert "**Did not merge** (found by merging):" in report
    assert "declined" not in report


def test_a_budget_stop_is_not_reported_as_nothing_conflicting(repo, tmp_path):
    analysis = _analyze(
        repo,
        tmp_path,
        ["feat-a", "feat-c"],
        resolver=_scripted_resolver([]),
        max_evaluations=0,
        check_base=False,
    )
    assert not analysis.exhausted
    report = markdown_report(analysis)
    assert "Every candidate merges and validates together" not in report
