"""Tiered validation and the cost model.

The claims worth gating, in order of how badly a regression would hurt:

1. the expensive tier runs on the frontier, not on the interior;
2. a set confirmed only at the cheap tier is never reported as validated;
3. the anytime bound is a real upper bound, and ``gap == 0`` really is a proof;
4. "keep this change" is a different question with a different answer;
5. cost estimates come from measurements, and an unmeasured tier is not free.
"""

import os

import pytest

from mergeset.base import Change, Evaluation, Verdict, set_key
from mergeset.cost import (
    UNMEASURED_TIER_SECONDS,
    MeasuredCost,
    cost_from_log,
    set_cost,
)
from mergeset.log import EvaluationLog, MemoryLines
from mergeset.tiers import (
    Tier,
    analyze_tiered,
    anytime_answer,
    best_set_including,
    chained_evaluate,
    tier_lines,
)
from mergeset.validation import (
    ValidationStage,
    merge_only_validation,
    staged_validation,
)

from conftest import py_command


# --------------------------------------------------------------------------
# The lever: cheap failures never reach the expensive tier
# --------------------------------------------------------------------------


def _oracle(conflicts, seen=None):
    conflicts = [frozenset(c) for c in conflicts]

    def evaluate(subset):
        subset = frozenset(subset)
        if seen is not None:
            seen.append(set_key(subset))
        bad = any(c <= subset for c in conflicts)
        return Evaluation(subset, Verdict.FAIL if bad else Verdict.PASS)

    return evaluate


def test_a_cheap_failure_is_never_paid_for_at_the_expensive_tier():
    deep_calls = []
    chained = chained_evaluate(
        [_oracle([{"a", "b"}]), _oracle([{"c"}], seen=deep_calls)]
    )
    assert chained(frozenset({"a", "b", "c"})).verdict is Verdict.FAIL
    assert deep_calls == [], "the deep tier ran on a set the screen already refuted"
    assert chained(frozenset({"a"})).verdict is Verdict.PASS
    assert deep_calls == [("a",)], "the deep tier must run on screen survivors"


def test_the_chain_reports_the_tier_that_actually_failed():
    """The failing tier's evaluation is what comes back, not a synthesized one."""
    deep = _oracle([{"x"}])
    chained = chained_evaluate([_oracle([]), deep])
    result = chained(frozenset({"x"}))
    assert result.verdict is Verdict.FAIL
    assert result.subset == frozenset({"x"})


# --------------------------------------------------------------------------
# The anytime answer
# --------------------------------------------------------------------------


TIERS = [Tier("unit", merge_only_validation()), Tier("e2e", merge_only_validation())]


def test_the_bound_is_an_upper_bound_and_a_zero_gap_is_a_proof():
    answer = anytime_answer(
        ["a", "b", "c"],
        [frozenset({"a", "b"})],
        weight=lambda c: 1.0,
        verified=[(frozenset({"b", "c"}), "e2e")],
        tiers=TIERS,
    )
    assert answer.bound == 2.0, "the heaviest set no conflict forbids has two changes"
    assert answer.best_weight == 2.0
    assert answer.gap == 0.0 and answer.optimal
    assert "provably maximal" in answer.summary()


def test_a_gap_stays_open_while_a_bigger_set_is_unrefuted():
    answer = anytime_answer(
        ["a", "b", "c"],
        [],  # nothing refuted yet
        weight=lambda c: 1.0,
        verified=[(frozenset({"a", "b"}), "e2e")],
        tiers=TIERS,
    )
    assert answer.bound == 3.0 and answer.gap == 1.0
    assert not answer.optimal


def test_a_tier_that_did_not_run_is_not_a_tier_that_passed():
    """A zero gap at the screen is not a proof about the deep tier."""
    answer = anytime_answer(
        ["a", "b", "c"],
        [frozenset({"a", "b"})],
        weight=lambda c: 1.0,
        verified=[(frozenset({"b", "c"}), "unit")],  # screen only
        tiers=TIERS,
    )
    assert answer.gap == 0.0, "nothing heavier is unrefuted"
    assert not answer.optimal, "but the deep tier never ran, so nothing is proven"
    assert not answer.full_depth
    assert "confirmed to tier `unit`" in answer.summary()


def test_depth_outranks_weight_when_choosing_the_best_answer():
    answer = anytime_answer(
        ["a", "b", "c"],
        [],
        weight=lambda c: 1.0,
        verified=[
            (frozenset({"a", "b", "c"}), "unit"),  # heavier, screen only
            (frozenset({"a"}), "e2e"),  # lighter, fully validated
        ],
        tiers=TIERS,
    )
    assert answer.best == frozenset({"a"})
    assert answer.full_depth


def test_pending_prices_what_closing_the_gap_would_cost():
    cost = MeasuredCost(declared={"e2e": 300.0})
    answer = anytime_answer(
        ["a", "b", "c"],
        [],
        weight=lambda c: 1.0,
        verified=[],
        tiers=TIERS,
        cost_model=cost,
        remaining_tiers=["e2e"],
    )
    assert answer.pending, "an unconfirmed candidate should be priced"
    assert answer.pending[0][1] == 300.0


# --------------------------------------------------------------------------
# "Keep this change" is a different question
# --------------------------------------------------------------------------


def test_the_best_set_keeping_a_change_is_not_reachable_by_adding_it():
    """The empirically important case, in miniature.

    ``h`` conflicts with ``a`` and ``b``. The unconstrained maximum is
    ``{a, b, c}``; adding ``h`` to it fails, and the best set containing ``h``
    is neither a superset nor a subset of it.
    """
    evaluate = _oracle([{"h", "a"}, {"h", "b"}])
    best, _, _ = best_set_including("abch", evaluate, must_include=["h"])
    assert best == frozenset({"c", "h"})


def test_a_required_change_that_cannot_be_kept_is_reported_as_such():
    evaluate = _oracle([{"h"}])  # h fails on its own
    best, conflicts, _ = best_set_including("abh", evaluate, must_include=["h"])
    assert best is None
    assert frozenset({"h"}) in conflicts


def test_required_changes_reuse_conflicts_the_main_search_already_found():
    seen = []
    evaluate = _oracle([{"h", "a"}], seen=seen)
    best, _, spent = best_set_including(
        "abch", evaluate, must_include=["h"], conflicts=[frozenset({"h", "a"})]
    )
    assert best == frozenset({"b", "c", "h"})
    assert spent == 1, f"seeded conflicts should make this one evaluation, not {spent}"


def test_must_include_rejects_a_change_that_is_not_a_candidate():
    with pytest.raises(ValueError, match="not candidates"):
        best_set_including("abc", _oracle([]), must_include=["nope"])


# --------------------------------------------------------------------------
# The cost model
# --------------------------------------------------------------------------


def test_an_unmeasured_undeclared_tier_is_not_free():
    """Otherwise a cost-ordered scheduler runs it first, for lack of data."""
    cost = MeasuredCost()
    assert cost.estimate("e2e", frozenset({"a"})) == UNMEASURED_TIER_SECONDS
    assert not cost.is_measured("e2e")


def test_measurements_beat_declarations_once_they_exist():
    cost = MeasuredCost(declared={"unit": 999.0})
    assert cost.estimate("unit", frozenset({"a"})) == 999.0
    cost.observe("unit", frozenset({"a"}), 40.0)
    cost.observe("unit", frozenset({"a"}), 44.0)
    assert cost.estimate("unit", frozenset({"a"})) == 42.0
    assert cost.is_measured("unit")


def test_the_pessimistic_estimate_covers_the_spread_a_fingerprinted_stage_causes():
    """Warm and cold runs of the same set differ by the skipped install.

    Nothing in the subset predicts which will happen, so the model cannot fit it
    away; the honest response is a second, higher number used for budget
    admission. These are the numbers a real run of this shape produces.
    """
    cost = MeasuredCost()
    for seconds in (27.2, 32.2, 32.2, 51.2):
        cost.observe("unit", frozenset({"a", "b"}), seconds)
    central = cost.estimate("unit", frozenset({"a", "b"}))
    assert 32 < central < 37, central
    assert cost.pessimistic("unit", frozenset({"a", "b"})) >= 51.2


def test_the_cost_model_is_fitted_from_the_evaluation_log_by_default():
    """The default is measured, not declared: the log has been storing this."""
    log = EvaluationLog(MemoryLines())
    log.record(Evaluation(frozenset({"a"}), Verdict.PASS, duration=40.0))
    log.record(Evaluation(frozenset({"a", "b", "c"}), Verdict.FAIL, duration=60.0))
    cost = cost_from_log(log, tier="unit")
    assert cost.estimate("unit", frozenset({"a", "b"})) == 50.0
    assert cost.is_measured("unit")


def test_a_full_verdict_costs_the_sum_of_its_tiers():
    cost = MeasuredCost(declared={"unit": 45.0, "e2e": 300.0})
    assert set_cost(cost, ["unit", "e2e"], frozenset({"a"})) == 345.0


def test_per_change_surcharges_are_added_to_the_tier_price():
    cost = MeasuredCost(declared={"unit": 10.0}, per_change={"heavy": 90.0})
    assert cost.estimate("unit", frozenset({"light"})) == 10.0
    assert cost.estimate("unit", frozenset({"light", "heavy"})) == 100.0


def test_the_cost_summary_says_where_each_number_came_from():
    cost = MeasuredCost(declared={"e2e": 300.0})
    cost.observe("unit", frozenset({"a"}), 45.0)
    summary = cost.summary()
    assert summary["unit"]["source"] == "measured"
    assert summary["e2e"]["source"] == "declared"


# --------------------------------------------------------------------------
# End to end, against a real repository
# --------------------------------------------------------------------------


def _changes(repo, names):
    return [Change(id=n, head=n, base="main") for n in names]


def _stage_validator(tmp_path, name, code):
    return staged_validation([ValidationStage(name, py_command(tmp_path, name, code))])


def test_tiers_keep_separate_logs_so_a_cheap_pass_answers_no_deep_question(
    repo, tmp_path
):
    """The whole point, end to end.

    ``feat-b`` and ``feat-d`` touch different files and pass the screen. A deep
    tier that fails whenever ``feat-d`` is present must be able to say so, which
    it cannot if a screen PASS has already been cached as *the* verdict.
    """
    deep = _stage_validator(
        tmp_path,
        "deep",
        "import os, sys\n" "sys.exit(1 if os.path.exists('new-d.txt') else 0)\n",
    )
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[Tier("screen", merge_only_validation()), Tier("deep", deep)],
        pairwise_preoracle=False,
        use_ci_status=False,
    )
    assert result.depth_reached == "deep"
    assert result.maximal_sets == [frozenset({"feat-b"})]
    assert result.verified_tier(frozenset({"feat-b"})) == "deep"
    # The screen said yes to the pair; the deep tier said no. Two logs, two facts.
    assert result.logs["screen"].exact(frozenset({"feat-b", "feat-d"})).ok
    assert not result.logs["deep"].exact(frozenset({"feat-b", "feat-d"})).ok
    assert result.answer.optimal


def test_an_unavailable_deep_tier_degrades_to_a_labelled_partial_answer(repo, tmp_path):
    """No container daemon today is not a reason to report a full verdict."""
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier("e2e", merge_only_validation(), available=lambda: False),
        ],
        pairwise_preoracle=False,
        use_ci_status=False,
    )
    assert result.depth_reached == "screen"
    assert "e2e" in result.skipped
    assert result.maximal_sets == [frozenset({"feat-b", "feat-d"})]
    # Reported, but never claimed as validated at the tier that matters.
    assert result.analysis.unverified_sets == []  # verified *at the depth reached*
    assert not result.answer.optimal and not result.answer.full_depth
    assert any("did not run" in note for note in result.analysis.notes)


def test_a_budget_too_small_for_one_deep_run_skips_the_tier_rather_than_lying(
    repo, tmp_path
):
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier("e2e", merge_only_validation(), cost=600.0),
        ],
        confirm_budget_seconds=10.0,
        pairwise_preoracle=False,
        use_ci_status=False,
    )
    assert result.depth_reached == "screen"
    assert "budget" in result.skipped["e2e"]
    assert not result.answer.optimal


def test_the_deep_tier_is_spent_on_the_frontier_not_on_the_interior(repo, tmp_path):
    """Count the runs, because this is the claim the design rests on.

    ``feat-a`` and ``feat-c`` conflict textually, so the screen refutes every
    set holding both — for free, before any tier runs. The deep tier should
    therefore be paid only for maximal screen survivors.
    """
    deep_runs = []
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-a", "feat-b", "feat-c", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier(
                "deep", lambda w: (deep_runs.append(w), merge_only_validation()(w))[1]
            ),
        ],
        use_ci_status=False,
    )
    assert result.depth_reached == "deep"
    frontier = {set_key(s) for s in result.maximal_sets}
    assert frontier == {
        ("feat-a", "feat-b", "feat-d"),
        ("feat-b", "feat-c", "feat-d"),
    }
    assert len(deep_runs) <= len(frontier) + 1, (
        f"the deep tier ran {len(deep_runs)} times for a frontier of "
        f"{len(frontier)}; it is paying for the search interior"
    )
    # The screen paid for the interior instead: strictly more evaluations.
    assert result.runs["screen"] > len(deep_runs)


def test_a_required_change_gets_its_own_answer_alongside_the_maximal_one(repo):
    """``feat-a`` and ``feat-c`` conflict textually; both cannot be kept.

    Asking to keep ``feat-c`` gives a *different, smaller* plan than the maximal
    one, and that smaller plan is the answer to the question that was asked.
    """
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-a", "feat-b", "feat-c", "feat-d"]),
        base="main",
        tiers=[Tier("screen", merge_only_validation())],
        must_include=["feat-c"],
        use_ci_status=False,
    )
    assert result.must_include == frozenset({"feat-c"})
    assert result.best_including == frozenset({"feat-b", "feat-c", "feat-d"})
    assert "feat-a" not in result.best_including
    assert any("keeps feat-c" in note for note in result.analysis.notes)


def test_analyze_tiered_refuses_arguments_the_tiers_own(repo):
    from mergeset.base import MergesetError

    with pytest.raises(MergesetError, match="owns `validate`"):
        analyze_tiered(
            repo,
            _changes(repo, ["feat-b"]),
            base="main",
            tiers=[Tier("screen", merge_only_validation())],
            validate=merge_only_validation(),
        )


def test_tier_logs_are_namespaced_per_tier():
    backing = {}
    tier_lines("/x/proj/widget", "unit", store=backing).append({"a": 1})
    tier_lines("/x/proj/widget", "e2e", store=backing).append({"a": 2})
    assert len(backing) == 2, "two tiers must not share one log key"
    assert all(key.endswith(".jsonl") for key in backing)


def test_tier_logs_default_outside_any_repository(tmp_path):
    """Same rule as every other artifact: derived data never lands in the repo."""
    lines = tier_lines(str(tmp_path), "unit")
    assert os.environ["MERGESET_DATA_DIR"] in os.path.abspath(lines.path)
    assert str(tmp_path) not in os.path.dirname(os.path.abspath(lines.path))
