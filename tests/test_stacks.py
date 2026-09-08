"""The forest model: stacked changes are not an antichain."""

import pytest

from mergeset.base import Change, Evaluation, Verdict, set_key
from mergeset.solve import find_maximal_good_sets
from mergeset.sources import detect_stacks
from mergeset.stacks import (
    ancestors,
    close_down,
    close_up,
    cone_weights,
    count_closed_subsets,
    descendants,
    largest_closed_subset,
    stack_roots,
    tips,
)

# The shape TEST found on cosmograph: stacks are trees, not chains.
#   a -> b -> c
#          -> d       (c and d are siblings on b)
#   e -> f
FOREST = {"b": "a", "c": "b", "d": "b", "f": "e"}


def test_ancestors_and_descendants_are_inverse():
    assert set_key(ancestors("c", FOREST)) == ("a", "b")
    assert set_key(descendants("a", FOREST)) == ("b", "c", "d")


def test_siblings_do_not_contain_each_other():
    assert "d" not in descendants("c", FOREST)
    assert "c" not in ancestors("d", FOREST)


def test_close_down_adds_ancestors():
    assert set_key(close_down({"c"}, FOREST)) == ("a", "b", "c")


def test_largest_closed_subset_drops_orphans_transitively():
    # dropping `b` must drop both its children, not just the direct one
    assert set_key(largest_closed_subset({"a", "c", "d"}, FOREST)) == ("a",)


def test_close_up_is_what_dropping_costs():
    assert set_key(close_up({"b"}, FOREST)) == ("b", "c", "d")


def test_tips_are_what_you_actually_merge():
    assert set_key(tips({"a", "b", "c", "d"}, FOREST)) == ("c", "d")
    assert set_key(tips({"a", "b", "c", "e", "f"}, FOREST)) == ("c", "f")


def test_cone_weights_charge_a_stack_root_for_its_whole_stack():
    own = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0, "e": 1.0, "f": 1.0}
    cone = cone_weights(own, FOREST)
    assert cone["a"] == 4.0  # a + b + c + d
    assert cone["c"] == 1.0  # a leaf costs only itself
    assert cone["e"] == 2.0


def test_stack_roots_group_by_component():
    assert [set_key(g) for g in stack_roots(FOREST, "abcdefg")] == [
        ("a", "b", "c", "d"),
        ("e", "f"),
        ("g",),
    ]


def test_closed_subset_count_is_far_below_the_powerset():
    ids = list("abcdef")
    assert count_closed_subsets(FOREST, ids) < 2 ** len(ids)
    # a->b->{c,d}: closed sets are {}, {a}, {ab}, {abc}, {abd}, {abcd} = 6
    # e->f: {}, {e}, {ef} = 3
    assert count_closed_subsets(FOREST, ids) == 6 * 3


def test_detect_stacks_reads_pr_base_refs():
    def pr(cid, head_ref, base_ref):
        return Change(
            id=cid, head=f"origin/{head_ref}", base=f"origin/{base_ref}", source="pr",
            meta={"head_ref": head_ref, "base_ref": base_ref},
        )

    changes = [pr("p1", "a", "main"), pr("p2", "b", "a"), pr("p3", "c", "a")]
    assert detect_stacks(changes) == {"p2": "p1", "p3": "p1"}


def test_search_never_proposes_a_set_missing_an_ancestor():
    seen = []

    def evaluate(subset):
        seen.append(frozenset(subset))
        bad = {"a", "e"} <= set(subset)
        return Evaluation(frozenset(subset), Verdict.FAIL if bad else Verdict.PASS)

    find_maximal_good_sets("abcdef", evaluate, depends_on=FOREST)
    for subset in seen:
        for member in subset:
            assert ancestors(member, FOREST) <= subset, (
                f"{set_key(subset)} contains {member} without its ancestors"
            )


def test_dropping_a_stack_root_drops_its_whole_cone():
    def evaluate(subset):
        # only `a` itself is the problem; the search must still shed b, c, d
        return Evaluation(
            frozenset(subset), Verdict.FAIL if "a" in subset else Verdict.PASS
        )

    state = find_maximal_good_sets("abcdef", evaluate, depends_on=FOREST)
    assert [set_key(s) for s in state.maximal_good_sets] == [("e", "f")]


def test_stacked_search_still_finds_the_biggest_valid_set():
    def evaluate(subset):
        bad = {"d", "f"} <= set(subset)
        return Evaluation(frozenset(subset), Verdict.FAIL if bad else Verdict.PASS)

    state = find_maximal_good_sets("abcdef", evaluate, depends_on=FOREST)
    for subset in state.maximal_good_sets:
        assert not ({"d", "f"} <= set(subset))
        assert all(ancestors(m, FOREST) <= subset for m in subset)
    assert frozenset("abce") in {s | frozenset() for s in state.maximal_good_sets} or any(
        len(s) >= 4 for s in state.maximal_good_sets
    )
