"""The search, tested without git: the oracle is just a set predicate."""

import itertools

import pytest

from mergeset.base import Evaluation, Verdict, set_key
from mergeset.log import EvaluationLog, MemoryLines
from mergeset.solve import (
    combine_components,
    find_maximal_good_sets,
    independent_components,
    minimal_hitting_sets,
    quickxplain,
    shrink_linear,
)


def oracle_from_conflicts(conflicts, counter=None):
    """An evaluator that fails exactly on supersets of any of `conflicts`."""
    conflicts = [frozenset(c) for c in conflicts]

    def evaluate(subset):
        if counter is not None:
            counter.append(frozenset(subset))
        bad = any(c <= subset for c in conflicts)
        return Evaluation(frozenset(subset), Verdict.FAIL if bad else Verdict.PASS)

    return evaluate


def test_quickxplain_finds_a_minimal_conflict():
    evaluate = oracle_from_conflicts([{"a", "c"}])
    assert quickxplain(evaluate, list("abcdefgh")) == frozenset({"a", "c"})


def test_quickxplain_agrees_with_linear_shrinking():
    conflicts = [{"b", "e"}]
    items = list("abcdef")
    assert quickxplain(oracle_from_conflicts(conflicts), items) == shrink_linear(
        oracle_from_conflicts(conflicts), items
    )


def test_quickxplain_is_cheaper_than_linear_on_wide_inputs():
    items = [f"c{i}" for i in range(32)]
    conflict = [{"c3", "c29"}]
    qx_calls, lin_calls = [], []
    quickxplain(oracle_from_conflicts(conflict, qx_calls), items)
    shrink_linear(oracle_from_conflicts(conflict, lin_calls), items)
    assert len(qx_calls) < len(lin_calls)


def test_minimal_hitting_sets_are_minimal_and_ordered():
    conflicts = [frozenset({"a", "b"}), frozenset({"b", "c"}), frozenset({"c", "d"})]
    got = [set_key(h) for h in itertools.islice(minimal_hitting_sets(conflicts), 5)]
    assert len(got[0]) == 2, "no single element hits all three conflicts"
    assert [len(h) for h in got] == sorted(len(h) for h in got), "not cheapest-first"
    for h in got:
        assert all(set(h) & c for c in conflicts), "not a hitting set"
        assert not any(set(other) < set(h) for other in got), "not minimal"


def test_minimal_hitting_sets_respect_weights():
    conflicts = [frozenset({"cheap", "precious"})]
    weight = {"cheap": 1.0, "precious": 100.0}.get
    first = next(minimal_hitting_sets(conflicts, weight=weight))
    assert first == frozenset({"cheap"})  # drop the cheap one


def test_no_conflicts_means_everything_merges():
    state = find_maximal_good_sets(list("abc"), oracle_from_conflicts([]))
    assert state.maximal_good_sets == [frozenset("abc")]
    assert state.evaluations == 1
    assert state.exhausted


def test_single_pairwise_conflict_yields_two_maximal_sets():
    state = find_maximal_good_sets(list("abc"), oracle_from_conflicts([{"a", "c"}]))
    assert [set_key(s) for s in state.maximal_good_sets] == [("a", "b"), ("b", "c")]
    assert [set_key(c) for c in state.conflicts] == [("a", "c")]


def test_triple_conflict_is_found_and_only_it():
    state = find_maximal_good_sets(
        list("abcd"), oracle_from_conflicts([{"a", "b", "c"}])
    )
    assert [set_key(c) for c in state.conflicts] == [("a", "b", "c")]
    assert [set_key(s) for s in state.maximal_good_sets] == [
        ("a", "b", "d"),
        ("a", "c", "d"),
        ("b", "c", "d"),
    ]


def test_known_conflicts_cost_no_evaluations():
    with_free = find_maximal_good_sets(
        list("abc"),
        oracle_from_conflicts([{"a", "c"}]),
        known_conflicts=[frozenset({"a", "c"})],
    )
    without = find_maximal_good_sets(list("abc"), oracle_from_conflicts([{"a", "c"}]))
    assert with_free.maximal_good_sets == without.maximal_good_sets
    assert with_free.evaluations < without.evaluations


def test_budget_stops_the_search_and_says_so():
    state = find_maximal_good_sets(
        list("abcdef"),
        oracle_from_conflicts([{"a", "b"}, {"c", "d"}, {"e", "f"}]),
        max_evaluations=1,
    )
    assert not state.exhausted
    assert "max_evaluations" in state.stopped_because


def test_max_sets_budget_returns_partial_results():
    state = find_maximal_good_sets(
        list("abcd"), oracle_from_conflicts([{"a", "b"}, {"c", "d"}]), max_sets=1
    )
    assert len(state.maximal_good_sets) == 1
    assert not state.exhausted


def test_everything_conflicts_with_base_leaves_only_singletons():
    conflicts = [{"a", "b"}, {"a", "c"}, {"b", "c"}]
    state = find_maximal_good_sets(list("abc"), oracle_from_conflicts(conflicts))
    assert {set_key(s) for s in state.maximal_good_sets} == {("a",), ("b",), ("c",)}


def test_log_caching_prevents_re_evaluation():
    calls = []
    log = EvaluationLog(MemoryLines())
    evaluate = log.caching(oracle_from_conflicts([{"a", "c"}], calls))
    find_maximal_good_sets(list("abcd"), evaluate)
    assert len(calls) == len(set(calls)), "a subset was evaluated twice"


def test_log_monotone_closure_skips_implied_sets():
    log = EvaluationLog(MemoryLines())
    log.record(Evaluation(frozenset("abcd"), Verdict.PASS))
    calls = []
    evaluate = log.caching(oracle_from_conflicts([], calls))
    assert evaluate(frozenset("ab")).verdict is Verdict.PASS
    assert calls == [], "a subset of a passing set should not be re-evaluated"


def test_independent_components_split_disjoint_file_sets():
    files = {"a": ["x.py"], "b": ["x.py", "y.py"], "c": ["z.py"], "d": []}
    components = independent_components(files, files.get)
    assert [set_key(c) for c in components] == [("a", "b"), ("c",), ("d",)]


def test_components_combine_into_global_maximal_sets():
    combined = combine_components([[frozenset("ab"), frozenset("b")], [frozenset("c")]])
    assert [set_key(s) for s in combined] == [("a", "b", "c")]


def test_component_decomposition_matches_the_monolithic_answer():
    conflicts = [{"a", "b"}, {"c", "d"}]
    monolithic = find_maximal_good_sets(list("abcd"), oracle_from_conflicts(conflicts))
    files = {"a": ["1"], "b": ["1"], "c": ["2"], "d": ["2"]}
    per_component = [
        find_maximal_good_sets(comp, oracle_from_conflicts(conflicts)).maximal_good_sets
        for comp in independent_components(files, files.get)
    ]
    decomposed = combine_components(per_component)
    assert {set_key(s) for s in decomposed} == {
        set_key(s) for s in monolithic.maximal_good_sets
    }


@pytest.mark.parametrize(
    "conflicts",
    [
        [{"a"}],
        [{"a"}, {"b", "c"}],
        [{"a", "b"}, {"b", "c"}, {"a", "c"}],
        [{"a", "b", "c"}, {"d"}],
    ],
)
def test_results_are_always_good_and_maximal(conflicts):
    """Brute force is the referee: every reported set is good and unextendable."""
    items = list("abcde")
    evaluate = oracle_from_conflicts(conflicts)
    state = find_maximal_good_sets(items, evaluate)
    for subset in state.maximal_good_sets:
        assert evaluate(subset).verdict is Verdict.PASS
        for extra in set(items) - subset:
            assert evaluate(subset | {extra}).verdict is Verdict.FAIL
    brute = {
        frozenset(c)
        for k in range(len(items) + 1)
        for c in itertools.combinations(items, k)
        if evaluate(frozenset(c)).verdict is Verdict.PASS
    }
    expected = {s for s in brute if not any(s < other for other in brute)}
    assert set(state.maximal_good_sets) == expected
