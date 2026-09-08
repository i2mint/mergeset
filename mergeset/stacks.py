"""Stacked changes: when the candidates are not independent.

A pull request opened against another pull request's branch already *contains*
it. That single fact breaks the assumption that any subset of the candidates is
a meaningful thing to evaluate, and it breaks it in three places at once:

- **Validity.** Asking for ``{616}`` when 616 is stacked on 604 on 587 really
  means ``{587, 604, 616}``. A valid set must be **downward-closed** under the
  parent relation. Note "downward-closed in a forest", not "a prefix of a
  chain": stacks branch, so two changes can be siblings on the same parent.
- **Cost.** Merging a stack's tip brings every ancestor with it, so merging the
  ancestors explicitly is wasted work and can perturb merge order. Reduce a set
  to its **tips** before merging.
- **Weight.** Dropping a change drops its whole descendant cone. Weighting
  changes independently lets a hitting set cheerfully discard thousands of lines
  while believing it discarded one small PR.

Discovering the relation is :func:`mergeset.sources.detect_stacks`; acting on it
is here. The dependency map is always ``child -> parent``.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set

from mergeset.base import ChangeId, ChangeSet, set_key

#: ``child -> parent``. A change absent from the mapping has no parent.
Dependencies = Mapping[ChangeId, ChangeId]


def ancestors(change: ChangeId, parents: Dependencies) -> ChangeSet:
    """Every change ``change`` is stacked on, transitively.

    >>> set_key(ancestors('c', {'c': 'b', 'b': 'a'}))
    ('a', 'b')
    """
    out: Set[ChangeId] = set()
    current = parents.get(change)
    while current is not None and current not in out:
        out.add(current)
        current = parents.get(current)
    return frozenset(out)


def descendants(change: ChangeId, parents: Dependencies) -> ChangeSet:
    """Every change stacked on ``change``, transitively — its *cone*.

    >>> set_key(descendants('a', {'c': 'b', 'b': 'a', 'd': 'a'}))
    ('b', 'c', 'd')
    """
    children: Dict[ChangeId, List[ChangeId]] = {}
    for child, parent in parents.items():
        children.setdefault(parent, []).append(child)
    out: Set[ChangeId] = set()
    stack = list(children.get(change, ()))
    while stack:
        node = stack.pop()
        if node in out:
            continue
        out.add(node)
        stack.extend(children.get(node, ()))
    return frozenset(out)


def close_down(subset: Iterable[ChangeId], parents: Dependencies) -> ChangeSet:
    """Add every ancestor, so the set becomes a valid thing to ask for.

    >>> set_key(close_down({'c'}, {'c': 'b', 'b': 'a'}))
    ('a', 'b', 'c')
    """
    subset = frozenset(subset)
    return subset | frozenset(
        a for member in subset for a in ancestors(member, parents)
    )


def largest_closed_subset(
    subset: Iterable[ChangeId], parents: Dependencies
) -> ChangeSet:
    """Drop members whose ancestors are missing — the set you can actually merge.

    This is the *other* way to make a set valid, and it is the one the solver
    needs: when the search decides to drop a parent, the descendants have to go
    too, and no amount of wanting them back changes that.

    >>> set_key(largest_closed_subset({'b', 'c'}, {'c': 'b', 'b': 'a'}))
    ()
    >>> set_key(largest_closed_subset({'a', 'b', 'd'}, {'c': 'b', 'b': 'a'}))
    ('a', 'b', 'd')
    """
    subset = set(subset)
    changed = True
    while changed:
        changed = False
        for member in list(subset):
            parent = parents.get(member)
            if parent is not None and parent not in subset:
                subset.discard(member)
                changed = True
    return frozenset(subset)


def close_up(subset: Iterable[ChangeId], parents: Dependencies) -> ChangeSet:
    """Add every descendant — what dropping these changes actually costs.

    >>> set_key(close_up({'a'}, {'c': 'b', 'b': 'a'}))
    ('a', 'b', 'c')
    """
    subset = frozenset(subset)
    return subset | frozenset(
        d for member in subset for d in descendants(member, parents)
    )


def tips(subset: Iterable[ChangeId], parents: Dependencies) -> ChangeSet:
    """The members of ``subset`` that nothing else in ``subset`` is stacked on.

    Merging these brings the rest along for free.

    >>> set_key(tips({'a', 'b', 'c'}, {'c': 'b', 'b': 'a'}))
    ('c',)
    >>> set_key(tips({'a', 'b', 'd'}, {'b': 'a', 'd': 'a'}))
    ('b', 'd')
    """
    subset = frozenset(subset)
    covered = frozenset(
        parents[member] for member in subset if parents.get(member) in subset
    )
    return subset - covered


def cone_weights(
    weights: Mapping[ChangeId, float], parents: Dependencies
) -> Dict[ChangeId, float]:
    """Re-weight each change by the cost of dropping its whole descendant cone.

    Dropping a stack's root drops the stack. The hitting set has to know that,
    or it will pick the "cheapest" change and take eight thousand lines with it.

    >>> cone_weights({'a': 1.0, 'b': 2.0}, {'b': 'a'})
    {'a': 3.0, 'b': 2.0}
    """
    return {
        change: weights.get(change, 1.0)
        + sum(weights.get(d, 1.0) for d in descendants(change, parents))
        for change in weights
    }


def stack_roots(parents: Dependencies, changes: Iterable[ChangeId]) -> List[ChangeSet]:
    """Group changes into stacks (connected components of the parent relation).

    >>> [set_key(g) for g in stack_roots({'b': 'a', 'd': 'c'}, 'abcde')]
    [('a', 'b'), ('c', 'd'), ('e',)]
    """
    changes = list(changes)
    groups: Dict[ChangeId, Set[ChangeId]] = {}
    for change in changes:
        root = change
        while parents.get(root) is not None:
            root = parents[root]
        groups.setdefault(root, set()).add(change)
    return sorted((frozenset(g) for g in groups.values()), key=lambda s: set_key(s))


def count_closed_subsets(parents: Dependencies, changes: Iterable[ChangeId]) -> int:
    """How many downward-closed subsets exist — the size of the real search space.

    Worth reporting: on a 15-change forest of four stacks this is 576 rather
    than 32768, which is the difference between "enumerate carefully" and
    "hopeless".

    >>> count_closed_subsets({'b': 'a'}, ['a', 'b'])
    3
    """
    changes = list(changes)
    children: Dict[ChangeId, List[ChangeId]] = {}
    for child, parent in parents.items():
        children.setdefault(parent, []).append(child)

    def count(node: ChangeId) -> int:
        """Closed subsets of the subtree at ``node``, given ``node`` is included."""
        total = 1
        for child in children.get(node, ()):
            total *= count(child) + 1  # child excluded, or any of its closed sets
        return total

    roots = [c for c in changes if parents.get(c) is None]
    total = 1
    for root in roots:
        total *= count(root) + 1
    return total
