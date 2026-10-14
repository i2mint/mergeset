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
    assert any("offered to the resolver once" in n for n in analysis.notes)


def test_without_a_resolver_the_preoracle_still_excludes(repo, tmp_path):
    analysis = _analyze(repo, tmp_path, ["feat-a", "feat-c"])
    assert [(a, b) for a, b, _ in analysis.textual_conflicts] == [
        ("feat-a", "feat-c")
    ]
    assert not any("offered to the resolver once" in n for n in analysis.notes)


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


def test_a_declining_resolver_is_asked_once_per_textual_pair(repo, tmp_path):
    """#47: not again for every superset holding the conflict."""
    calls = []

    def declines(worktree, files):
        calls.append(sorted(files))
        return False, "no"

    analysis = _analyze(
        repo,
        tmp_path,
        ["feat-a", "feat-b", "feat-c", "feat-d"],
        resolver=declines,
        decompose=False,
    )
    assert len(calls) == 1, calls
    assert frozenset({"feat-a", "feat-c"}) in analysis.conflicts
    assert sorted(map(sorted, analysis.maximal_sets)) == [
        ["feat-a", "feat-b", "feat-d"],
        ["feat-b", "feat-c", "feat-d"],
    ]
    assert not analysis.textual_conflicts
    [note] = [n for n in analysis.notes if "offered to the resolver once" in n]
    assert "1 failed" in note


def test_a_resolved_pair_stays_in_play(repo, tmp_path):
    calls = []
    analysis = _analyze(
        repo,
        tmp_path,
        ["feat-a", "feat-b", "feat-c"],
        resolver=_scripted_resolver(calls),
    )
    assert analysis.maximal_sets == [frozenset({"feat-a", "feat-b", "feat-c"})]
    assert not analysis.conflicts


def test_the_offering_spends_from_the_evaluation_budget(repo, tmp_path):
    calls = []

    def declines(worktree, files):
        calls.append(1)
        return False, "no"

    analysis = _analyze(
        repo,
        tmp_path,
        ["feat-a", "feat-b", "feat-c"],
        resolver=declines,
        max_evaluations=1,
    )
    assert len(calls) == 1
    [note] = [n for n in analysis.notes if "offered to the resolver once" in n]
    assert "stopped early" in note or analysis.searches[0].stopped_because


def test_offer_once_skips_pairs_holding_a_declined_singleton_and_stops_on_error():
    from mergeset.analysis import _offer_once
    from mergeset.base import Evaluation, Verdict

    seen = []

    def evaluate(subset):
        seen.append(subset)
        verdict = Verdict.FAIL if "x" in subset else Verdict.PASS
        if subset == frozenset({"c", "d"}):
            verdict = Verdict.ERROR
        return Evaluation(subset, verdict)

    offered = _offer_once(
        evaluate, ["x"], [("x", "a"), ("a", "b"), ("c", "d"), ("e", "f")], parents={}
    )
    assert offered.declined == [frozenset({"x"})]
    assert seen == [
        frozenset({"x"}),
        frozenset({"a", "b"}),
        frozenset({"c", "d"}),
    ]


def test_a_pair_holding_an_excluded_change_is_not_offered(repo, tmp_path):
    calls = []

    def declines(worktree, files):
        calls.append(sorted(files))
        return False, "no"

    analysis = analyze(
        repo,
        [
            Change(id="feat-a", head="feat-a", base="main", meta={"ci": "failure"}),
            Change(id="feat-c", head="feat-c", base="main"),
        ],
        base="main",
        log=EvaluationLog(str(tmp_path / "eval.jsonl")),
        validate=merge_only_validation(),
        resolver=declines,
    )
    assert not calls
    assert analysis.maximal_sets == [frozenset({"feat-c"})]


def test_offer_once_records_the_change_set_not_its_stack_closure():
    from mergeset.analysis import _offer_once
    from mergeset.base import Evaluation, Verdict

    seen = []

    def evaluate(subset):
        seen.append(subset)
        return Evaluation(subset, Verdict.FAIL if "c" in subset else Verdict.PASS)

    offered = _offer_once(
        evaluate, ["c"], [("p", "y")], parents={"c": "p"}
    )
    assert seen == [frozenset({"c", "p"}), frozenset({"p", "y"})]
    assert offered.declined == [frozenset({"c"})]


def test_the_note_does_not_claim_the_rest_merged_after_an_error():
    from mergeset.analysis import _offer_once
    from mergeset.base import Evaluation, Verdict

    offered = _offer_once(
        lambda s: Evaluation(s, Verdict.ERROR, note="boom"), [], [("a", "b")], parents={}
    )
    assert "stopped on an evaluation that could not be performed (boom)" in offered.note
    assert "the rest merged" not in offered.note


def test_a_set_whose_stack_closure_holds_a_known_conflict_is_not_offered():
    from mergeset.analysis import _offer_once
    from mergeset.base import Evaluation, Verdict

    seen = []

    def evaluate(subset):
        seen.append(subset)
        return Evaluation(subset, Verdict.PASS)

    # C is stacked on P, and P is already excluded (e.g. its CI is red).
    offered = _offer_once(
        evaluate,
        [],
        [("c", "x")],
        parents={"c": "p"},
        known=[frozenset({"p"})],
    )
    assert not seen and not offered.declined
