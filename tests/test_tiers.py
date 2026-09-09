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

from mergeset.base import Change, Evaluation, ValidationOutcome, Verdict, set_key
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
    assert answer.bound == 2.0, "nothing heavier than two changes is unrefuted"
    # The gap is measured against what has been confirmed at FULL depth, and
    # nothing has been. Subtracting a screen-only weight from the bound is
    # comparing two different things, and produced a negative gap whenever the
    # deep tier refuted what the screen had accepted.
    assert answer.gap == 2.0, "the deep tier has confirmed nothing at all"
    assert not answer.optimal, "the deep tier never ran, so nothing is proven"
    assert not answer.full_depth
    assert "confirmed to tier `unit`" in answer.summary()

    # And the case where the gap alone would say "done": everything is refuted,
    # so the bound is zero -- but the deep tier still never ran, and a zero gap
    # is only a certificate together with full depth.
    refuted = anytime_answer(
        ["a"],
        [frozenset({"a"})],
        weight=lambda c: 1.0,
        verified=[(frozenset(), "unit")],
        tiers=TIERS,
    )
    assert refuted.bound == 0.0 and refuted.gap == 0.0
    assert not refuted.optimal, "a zero gap at the screen proves nothing at depth"


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


def test_a_negative_per_change_surcharge_cannot_produce_a_negative_price():
    """Finding 13. The clamp was applied before the surcharges, not after."""
    cost = MeasuredCost(declared={"unit": 10.0}, per_change={"x": -50.0})
    assert cost.estimate("unit", frozenset({"x"})) == 0.0


def test_an_estimate_never_falls_below_the_fastest_run_ever_seen():
    """Finding 6. A zero price made a budget check conclude "unlimited"."""
    cost = MeasuredCost()
    for size, seconds in [(1, 40.0), (2, 35.0), (3, 30.0)]:
        cost.observe("unit", frozenset(range(size)), seconds)
    assert cost.estimate("unit", frozenset(range(50))) >= 30.0


def test_per_change_surcharges_are_added_to_the_tier_price():
    cost = MeasuredCost(declared={"unit": 10.0}, per_change={"heavy": 90.0})
    assert cost.estimate("unit", frozenset({"light"})) == 10.0
    assert cost.estimate("unit", frozenset({"light", "heavy"})) == 100.0


def test_observe_accepts_a_per_stage_breakdown_so_issue_17_lands_as_data():
    """The seam finding: `observe(..., seconds: float)` would have been burned.

    Per-stage durations (i2mint/mergeset#17) must land as data, not as a change
    to a signature already published to PyPI.
    """
    cost = MeasuredCost()
    cost.observe("unit", frozenset({"a"}), {"setup": 33.0, "build": 9.0, "test": 6.0})
    assert cost.estimate("unit", frozenset({"a"})) == 48.0


def test_the_observation_list_is_not_public_api():
    """Its shape is exactly what #17 changes, so it must not be an interface."""
    cost = MeasuredCost()
    cost.observe("unit", frozenset({"a"}), 10.0)
    assert not hasattr(cost, "observations")
    assert cost.runs("unit") == 1
    assert cost.summary()["unit"]["runs"] == 1


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
    # Reported, and NOT claimed as validated: the tier that was asked for never
    # ran, so "verified at the depth reached" is not a claim worth making.
    assert result.analysis.unverified_sets == result.maximal_sets
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


def test_the_screen_pays_the_interior_and_the_deep_tier_does_not(repo, tmp_path):
    """Count the runs, because this is the claim the design rests on.

    ``feat-a`` and ``feat-c`` conflict textually, so the screen refutes every set
    holding both — for free, before any tier runs. The deep tier here agrees with
    the screen, so there is no deep-only conflict and nothing to shrink at depth:
    the deep tier should be paid for the frontier and nothing else.
    """
    deep_runs = []
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-a", "feat-b", "feat-c", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier(
                "deep",
                lambda w: (deep_runs.append(w), merge_only_validation()(w))[1],
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
    # +1 for the tier's own base check, which is a real evaluation.
    assert len(deep_runs) <= len(frontier) + 1, (
        f"the deep tier ran {len(deep_runs)} times for a frontier of "
        f"{len(frontier)}; it is paying for the search interior"
    )
    assert result.runs["screen"] > len(deep_runs)


def test_a_deep_only_conflict_does_cost_deep_evaluations_and_we_say_so(repo, tmp_path):
    """The honest other half — the claim is bounded, not absolute.

    A conflict only the deep tier can see has to be *shrunk* at deep prices, so
    the deep tier necessarily touches interior sets. The module docstring used to
    say the expensive tier runs "never on the interior", which this refutes. What
    survives is the useful half: the screen's own interior is free, so the deep
    tier still runs far less than the screen.
    """
    deep_runs = []

    def deep(worktree):
        deep_runs.append(worktree)
        # feat-b and feat-d touch different files, so no cheap oracle can see
        # this: it is exactly a semantic conflict.
        both = os.path.exists(os.path.join(worktree, "new-d.txt")) and (
            open(os.path.join(worktree, "other.txt")).read().startswith("changed")
        )
        return ValidationOutcome(
            ok=not both, failing_tests=["deep: pair"] if both else []
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
    assert frozenset({"feat-b", "feat-d"}) not in result.maximal_sets
    assert deep_runs, "a deep-only conflict has to be found at deep prices"
    # The point: the deep tier ran more times than there are answers, because
    # shrinking a conflict the screen cannot see is interior work at deep prices.
    assert len(deep_runs) > len(result.maximal_sets)


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


def test_analyze_tiered_refuses_log_path_rather_than_ignoring_it(repo, tmp_path):
    """One path cannot hold several tiers, and a silent discard is worse.

    Found by asking what a CLI adapter would have to pass — the surface audit
    the seams exist to survive. `analyze` is handed the screen tier's log
    explicitly, so `log_path` would have been dropped without a word.
    """
    from mergeset.base import MergesetError

    with pytest.raises(MergesetError, match="owns `log_path`"):
        analyze_tiered(
            repo,
            _changes(repo, ["feat-b"]),
            base="main",
            tiers=[Tier("screen", merge_only_validation())],
            log_path=str(tmp_path / "one.jsonl"),
        )


def test_a_stacked_repo_does_not_get_a_non_maximal_constrained_answer():
    """Finding 1. Closure shrinks proposals *after* the weight ordering is fixed.

    `q1` and `q2` are stacked on `p`. Conflicts are {a,p} and {b,q1}. The hitting
    set ('b','p') is enumerated first and closes to just ('a',) -- but ('a','b')
    passes and is strictly bigger. Returning the first passing proposal is
    therefore returning a set short, which is the bug `solve.py`'s
    `_grow_within_known` was written to prevent.
    """
    parents = {"q1": "p", "q2": "p"}
    conflicts = [frozenset({"a", "p"}), frozenset({"b", "q1"})]
    evaluate = _oracle(conflicts)
    best, _, _ = best_set_including(
        ["a", "b", "p", "q1", "q2"],
        evaluate,
        must_include=["a"],
        # Seeded, because the bug is in the enumeration order over *known*
        # conflicts: ('b','p') is proposed before ('p','q1'), and closure shrinks
        # its complement to ('a',) after the weight ordering is already fixed.
        conflicts=conflicts,
        depends_on=parents,
    )
    assert best == frozenset({"a", "b"}), set_key(best)


def test_budget_admission_prices_a_deep_tier_from_its_own_log(repo, tmp_path):
    """Finding 2. The log was only read *after* the tier had run.

    So admission priced every deep tier from `declared` or the 60 s default even
    when its log held real timings, and the docstring's promise -- "measurements
    from one run price the next" -- was false.
    """
    log = EvaluationLog(tier_lines(repo, "deep"))
    for _ in range(5):
        log.record(Evaluation(frozenset({"feat-b"}), Verdict.PASS, duration=300.0))
    cost = MeasuredCost()
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier("deep", merge_only_validation()),
        ],
        cost_model=cost,
        # 200 s is refused outright at the logged price of ~300 s a run, and
        # would have admitted three runs at the 60 s unmeasured default. That
        # gap is the whole test.
        confirm_budget_seconds=200.0,
        pairwise_preoracle=False,
        use_ci_status=False,
    )
    assert cost.is_measured("deep"), "the deep tier's own log was never read"
    assert cost.runs("deep") == 5, "priced before the tier ran, not after"
    assert cost.pessimistic("deep", frozenset({"feat-b"})) >= 300.0
    assert result.depth_reached == "screen"
    assert "budget" in result.skipped["deep"]


def test_the_must_include_phase_obeys_the_seconds_budget(repo, tmp_path):
    """Finding 3. It was handed `confirm_max_runs` and nothing else.

    So a budget expressed in seconds -- the documented way to express one --
    capped stage 2 and left the constrained search completely unbounded.
    """
    deep_runs = []
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-a", "feat-b", "feat-c", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier(
                "deep",
                lambda w: (deep_runs.append(w), merge_only_validation()(w))[1],
                cost=100.0,
            ),
        ],
        must_include=["feat-c"],
        confirm_budget_seconds=250.0,
        use_ci_status=False,
    )
    # 250 s, 100 s a run, one reserved for the base check -> one search run.
    assert len(deep_runs) <= 3, f"{len(deep_runs)} deep runs against a 250 s budget"
    assert result.must_include == frozenset({"feat-c"})


def test_a_deep_tier_red_on_the_base_is_refused_not_reported_as_a_finding(
    repo, tmp_path
):
    """Finding: ADR-0018 one level up, found while reading #21.

    A deep tier that fails on the base alone makes every frontier set fail. Left
    unchecked the run reports "nothing passes deep" as a *result*, which is
    indistinguishable from a real answer precisely where nobody can cheaply
    re-run the tier by hand.
    """
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier("deep", lambda w: ValidationOutcome(ok=False, returncode=2)),
        ],
        pairwise_preoracle=False,
        use_ci_status=False,
    )
    assert result.depth_reached == "screen"
    assert "base alone" in result.skipped["deep"]
    assert result.maximal_sets == [frozenset({"feat-b", "feat-d"})]
    assert not result.answer.optimal
    assert any("did not run" in note for note in result.analysis.notes)


def test_tier_names_that_differ_only_in_case_are_rejected():
    """Finding 5. `e2e` and `E2E` are one file on macOS and Windows.

    Two tiers sharing a log is a cheap PASS answering an expensive question --
    the one thing this module exists to prevent -- on the default filesystem of
    two of three platforms.
    """
    with pytest.raises(ValueError, match="key-safe"):
        analyze_tiered(
            ".",
            [Change(id="x", head="x", base="main")],
            tiers=[
                Tier("e2e", merge_only_validation()),
                Tier("E2E", merge_only_validation()),
            ],
        )


def test_tier_names_cannot_escape_the_store_namespace():
    backing = {}
    tier_lines("/x/proj/widget", "a/b", store=backing).append({"a": 1})
    tier_lines("/x/proj/widget", "x/../y", store=backing).append({"a": 2})
    assert all("/" not in key.rsplit(".", 2)[-2] for key in backing)
    assert len(backing) == 2, "two unsafe names must not flatten onto one key"
    with pytest.raises(ValueError, match="cannot be blank"):
        tier_lines("/x/proj/widget", "   ", store=backing)


def test_a_cost_model_that_is_not_a_MeasuredCost_is_not_double_counted(repo):
    """Finding 7. The isinstance guard covered the reset but not the re-observe.

    Seam 2 publishes a `CostModel` protocol with no `reset`, so the facade must
    not need one -- otherwise every third-party model is fitted on duplicates.
    """

    class Counting:
        def __init__(self):
            self.seen = []

        def estimate(self, tier, subset):
            return 1.0

        def pessimistic(self, tier, subset):
            return 1.0

        def observe(self, tier, subset, seconds):
            self.seen.append((tier, len(subset)))

        def is_measured(self, tier):
            return bool(self.seen)

    cost = Counting()
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-a", "feat-b", "feat-c", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier("deep", merge_only_validation()),
        ],
        cost_model=cost,
        must_include=["feat-c"],
        use_ci_status=False,
    )
    rows = sum(len(log) for log in result.logs.values())
    assert (
        len(cost.seen) == rows
    ), f"{len(cost.seen)} observe() calls for {rows} log rows"


def test_the_bound_respects_stacks_so_the_certificate_is_reachable():
    """Finding 8. Without closure the bound names a set that can never land."""
    answer = anytime_answer(
        ["a", "b"],
        [frozenset({"a"})],
        weight=lambda c: 1.0,
        verified=[(frozenset(), "e2e")],
        tiers=TIERS,
        depends_on={"b": "a"},
    )
    assert answer.bound_set == frozenset(), "b cannot land without a"
    assert answer.bound == 0.0
    assert answer.optimal, "the empty set really is the maximum here"


def test_negative_weights_are_refused_rather_than_silently_breaking_the_bound():
    """Finding 10. Cheapest-first hitting sets are Dijkstra; negative edges break it.

    The failure was silent and in the dangerous direction: `bound` below the true
    optimum, reported as `provably maximal`.
    """
    with pytest.raises(ValueError, match="non-negative"):
        anytime_answer(
            ["a", "b"],
            [frozenset({"a"})],
            weight=lambda c: -3.0 if c == "b" else 1.0,
            verified=[],
            tiers=TIERS,
        )


def test_a_skipped_tier_is_never_reported_as_verified(repo):
    """Finding 9. The components shortcut applied even at a depth never reached.

    With a merge-only screen, `components_combined` is True by contract, and the
    shortcut then cleared `unverified_sets` for an answer the requested deep tier
    had never seen.
    """
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier("e2e", merge_only_validation(), available=lambda: False),
        ],
        use_ci_status=False,
    )
    assert result.analysis.unverified_sets == result.maximal_sets
    assert all(not plan["verified"] for plan in result.analysis.merge_plan())


def test_a_deep_tier_that_confirms_nothing_does_not_claim_it_did(repo):
    """Finding 4. The note was decided by "the last tier was entered"."""
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[
            Tier("screen", merge_only_validation()),
            Tier("deep", lambda w: ValidationOutcome(ok=False, returncode=1)),
        ],
        check_base=False,
        pairwise_preoracle=False,
        use_ci_status=False,
    )
    claims = [
        n
        for n in result.analysis.notes
        if "; every set below was confirmed at the deepest tier" in n
    ]
    assert not claims, claims
    assert result.answer.gap >= 0, "a screen-only best is not comparable to the bound"


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
