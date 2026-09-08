"""The search: from expensive yes/no evaluations to maximal good sets.

Vocabulary (standard in the MUS/MSS literature):

- a **conflict** is a minimal *bad* set (an MUS): remove any member and it stops
  being bad;
- a **maximal good set** is a good set that cannot be grown (an MSS);
- by Reiter's hitting-set duality, the complement of a maximal good set is
  exactly a minimal hitting set of the conflicts.

So the loop is: propose the complement of the cheapest minimal hitting set of
the conflicts known so far; evaluate it; if it fails, shrink the failure to a
new conflict (QuickXplain) and propose again; if it passes, it is a maximal good
set — record it and ask for the next-cheapest hitting set.

Nothing here knows about git. The only thing it needs is ``evaluate(subset) ->
Evaluation``, which is why the whole package is testable without a repository.
"""

from __future__ import annotations

import heapq
import itertools
import time
from dataclasses import dataclass, field
from typing import (
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from mergeset.base import ChangeId, ChangeSet, Evaluation, Verdict, set_key
from mergeset.stacks import Dependencies, close_down, close_up, largest_closed_subset

Evaluate = Callable[[ChangeSet], Evaluation]


# --------------------------------------------------------------------------
# Conflict extraction
# --------------------------------------------------------------------------


def quickxplain(
    evaluate: Evaluate,
    candidates: Sequence[ChangeId],
    *,
    background: ChangeSet = frozenset(),
) -> ChangeSet:
    """Shrink a known-bad set to one minimal conflict, in O(k log n) evaluations.

    Junker's QuickXplain: recursive halving that costs ``O(k log(n/k))``
    evaluations for a conflict of size ``k`` among ``n`` candidates, rather than
    the ``O(n)`` of naive one-at-a-time removal.

    Args:
        evaluate: The (cached) oracle.
        candidates: Members that may be part of the conflict.
        background: Members always present and assumed not, on their own, bad.

    Returns:
        A minimal subset ``C`` of ``candidates`` with ``background | C`` bad.

    >>> bad_pairs = [{'a', 'c'}]
    >>> def ev(s):
    ...     ok = not any(p <= set(s) for p in bad_pairs)
    ...     return Evaluation(s, Verdict.PASS if ok else Verdict.FAIL)
    >>> sorted(quickxplain(ev, ['a', 'b', 'c', 'd']))
    ['a', 'c']
    """
    candidates = list(candidates)
    if not candidates:
        return frozenset()

    def bad(subset: ChangeSet) -> bool:
        return evaluate(frozenset(subset)).verdict is Verdict.FAIL

    def _qx(bg: ChangeSet, delta: bool, cands: List[ChangeId]) -> ChangeSet:
        if delta and bad(bg):
            return frozenset()
        if len(cands) == 1:
            return frozenset(cands)
        mid = len(cands) // 2
        left, right = cands[:mid], cands[mid:]
        d1 = _qx(bg | frozenset(left), bool(left), right)
        d2 = _qx(bg | d1, bool(d1), left)
        return d1 | d2

    return _qx(frozenset(background), False, candidates)


def shrink_linear(
    evaluate: Evaluate,
    candidates: Sequence[ChangeId],
    *,
    background: ChangeSet = frozenset(),
) -> ChangeSet:
    """One-at-a-time conflict shrinking: ``n`` evaluations, dead simple.

    Kept because it is the obviously-correct reference that
    :func:`quickxplain` is checked against, and because for very small ``n`` it
    is not actually slower.
    """
    current = list(candidates)
    for member in list(candidates):
        trial = frozenset(background) | (frozenset(current) - {member})
        if evaluate(trial).verdict is Verdict.FAIL:
            current.remove(member)
    return frozenset(current)


# --------------------------------------------------------------------------
# Hitting sets (Reiter's HS-tree, best-first by weight)
# --------------------------------------------------------------------------


def minimal_hitting_sets(
    conflicts: Sequence[ChangeSet],
    *,
    weight: Optional[Callable[[ChangeId], float]] = None,
    limit: Optional[int] = None,
) -> Iterator[ChangeSet]:
    """Yield minimal hitting sets of ``conflicts``, cheapest total weight first.

    A hitting set touches every conflict; its complement is therefore a set with
    no known conflict inside it. Enumerating hitting sets cheapest-first means
    the solver proposes dropping the *least valuable* changes first.

    >>> hs = minimal_hitting_sets([frozenset({'a', 'b'}), frozenset({'b', 'c'})])
    >>> [sorted(h) for h in itertools.islice(hs, 3)]
    [['b'], ['a', 'c']]
    """
    conflicts = [frozenset(c) for c in conflicts if c]
    if not conflicts:
        yield frozenset()
        return
    weight = weight or (lambda _: 1.0)
    seen: Set[ChangeSet] = set()
    found: List[ChangeSet] = []
    heap: List[Tuple[float, int, ChangeSet]] = []
    counter = itertools.count()
    heapq.heappush(heap, (0.0, next(counter), frozenset()))
    n_yielded = 0
    while heap:
        cost, _, node = heapq.heappop(heap)
        unhit = next((c for c in conflicts if not (c & node)), None)
        if unhit is None:
            if any(prior <= node for prior in found):
                continue  # not minimal
            found.append(node)
            n_yielded += 1
            yield node
            if limit is not None and n_yielded >= limit:
                return
            continue
        for member in sorted(unhit):
            child = node | {member}
            if child in seen:
                continue
            seen.add(child)
            heapq.heappush(heap, (cost + weight(member), next(counter), child))


# --------------------------------------------------------------------------
# The main loop
# --------------------------------------------------------------------------


@dataclass
class SearchState:
    """Everything the search accumulated. Derived entirely from the log."""

    conflicts: List[ChangeSet] = field(default_factory=list)
    maximal_good_sets: List[ChangeSet] = field(default_factory=list)
    evaluations: int = 0
    elapsed: float = 0.0
    exhausted: bool = False  # search space fully covered (not budget-truncated)
    stopped_because: str = ""
    #: Set when an evaluation could not be performed at all. The results below
    #: are not wrong so much as unfinished, and must not be presented as an
    #: answer: "we could not run the experiment" is not "the experiment failed".
    error: str = ""

    def add_conflict(self, conflict: ChangeSet) -> None:
        """Add ``conflict``, keeping the list free of non-minimal members."""
        if not conflict or any(c <= conflict for c in self.conflicts):
            return
        self.conflicts = [c for c in self.conflicts if not conflict < c]
        self.conflicts.append(conflict)


def find_maximal_good_sets(
    changes: Iterable[ChangeId],
    evaluate: Evaluate,
    *,
    known_conflicts: Iterable[ChangeSet] = (),
    depends_on: Optional[Dependencies] = None,
    weight: Optional[Callable[[ChangeId], float]] = None,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    shrink: Callable[..., ChangeSet] = quickxplain,
    suspects: Optional[Callable[[Evaluation, ChangeSet], ChangeSet]] = None,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> SearchState:
    """Enumerate maximal good subsets of ``changes``, cheapest-dropped first.

    Args:
        changes: The change ids in play.
        evaluate: The (cached, log-backed) oracle.
        known_conflicts: Conflicts already known for free — e.g. textual
            ``git merge-tree`` conflicts and singletons whose own CI is red.
            These cost zero evaluations and prune enormously.
        depends_on: ``child -> parent`` for stacked changes. When given, only
            downward-closed sets are ever proposed (a change is never evaluated
            without the changes it is built on) and dropping a change implicitly
            drops everything stacked on it. See :mod:`mergeset.stacks`.
        weight: ``id -> cost of dropping it``. Higher means "keep me".
        max_evaluations, max_seconds, max_sets: Budgets. Whichever trips first
            stops the search; partial results are always returned.
        shrink: Conflict-minimization strategy (:func:`quickxplain` by default).
        suspects: ``(failed evaluation, the set) -> the changes it implicates``.
            Lets the search shrink within the implicated changes instead of
            halving the whole set. A wrong hint costs one wasted check and then
            falls back; see :mod:`mergeset.attribution`.
        on_event: ``(event_name, payload)`` progress callback.

    Returns:
        A :class:`SearchState`. ``exhausted`` says whether the answer is
        complete or merely the best found within budget.

    >>> bad = [{'a', 'c'}]
    >>> def ev(s):
    ...     ok = not any(p <= set(s) for p in bad)
    ...     return Evaluation(s, Verdict.PASS if ok else Verdict.FAIL)
    >>> state = find_maximal_good_sets(['a', 'b', 'c'], ev)
    >>> [set_key(s) for s in state.maximal_good_sets]
    [('a', 'b'), ('b', 'c')]
    >>> [set_key(c) for c in state.conflicts]
    [('a', 'c')]
    """
    all_changes = frozenset(changes)
    parents = {
        child: parent
        for child, parent in (depends_on or {}).items()
        if child in all_changes and parent in all_changes
    }
    state = SearchState()
    for c in known_conflicts:
        state.add_conflict(frozenset(c))
    started = time.time()
    emit = on_event or (lambda name, payload: None)

    def budget_exceeded() -> Optional[str]:
        if max_evaluations is not None and state.evaluations >= max_evaluations:
            return f"max_evaluations ({max_evaluations}) reached"
        if max_seconds is not None and time.time() - started >= max_seconds:
            return f"max_seconds ({max_seconds}) reached"
        if max_sets is not None and len(state.maximal_good_sets) >= max_sets:
            return f"max_sets ({max_sets}) reached"
        return None

    def counted_evaluate(subset: ChangeSet) -> Evaluation:
        # Shrinking proposes arbitrary subsets, and an arbitrary subset of a
        # stack is a fiction: merging a tip brings its ancestors whether or not
        # they were named. Evaluating the closure means the log records what was
        # actually merged, and it collapses sets that differ only in labels onto
        # one cache entry -- two of eleven evaluations in one real run were
        # duplicates for exactly this reason.
        if parents:
            subset = close_down(subset, parents)
        result = evaluate(subset)
        if not result.cached:
            state.evaluations += 1  # only real runs cost anything
        emit("evaluated", {"subset": set_key(subset), "verdict": result.verdict.value})
        return result

    # Complements of minimal hitting sets are the only candidates worth trying.
    # The conflict list grows as we go, so the enumeration is restarted each
    # time it changes; `tried` keeps the restarts from re-proposing old ideas.
    tried: Set[ChangeSet] = set()
    while True:
        reason = budget_exceeded()
        if reason:
            state.stopped_because = reason
            break
        candidate = _next_candidate(all_changes, state, tried, weight, parents)
        if candidate is None:
            state.exhausted = True
            state.stopped_because = "search space exhausted"
            break
        tried.add(candidate)
        result = counted_evaluate(candidate)
        if result.verdict is Verdict.PASS:
            grown = _grow_within_known(candidate, all_changes, state, parents)
            if grown != candidate and counted_evaluate(grown).verdict is Verdict.PASS:
                candidate = grown
                tried.add(grown)
            state.maximal_good_sets.append(candidate)
            emit("maximal_good_set", {"subset": set_key(candidate)})
        elif result.verdict is Verdict.FAIL:
            hint = _suspects(result, candidate)
            if not hint and suspects is not None:
                hint = suspects(result, candidate) or frozenset()
            conflict = shrink(counted_evaluate, sorted(hint or candidate))
            if hint and conflict and not _is_bad(counted_evaluate, conflict):
                # The hint was wrong; fall back to the whole candidate.
                conflict = shrink(counted_evaluate, sorted(candidate))
            state.add_conflict(conflict)
            emit("conflict", {"subset": set_key(conflict)})
        else:
            # ERROR carries no information about the changes at all, and a run
            # that keeps going past one reports confident nonsense: every
            # untestable set looks bad, and "0 of 15 mergeable, complete" is the
            # result. Stop, and say what went wrong.
            state.error = result.note or "an evaluation could not be performed"
            state.stopped_because = f"aborted: {state.error}"
            emit("aborted", {"subset": set_key(candidate), "error": state.error})
            break

    state.elapsed = time.time() - started
    state.maximal_good_sets = _keep_maximal(state.maximal_good_sets)
    return state


def _is_bad(evaluate: Evaluate, subset: ChangeSet) -> bool:
    return evaluate(subset).verdict is Verdict.FAIL


def _suspects(result: Evaluation, candidate: ChangeSet) -> Optional[ChangeSet]:
    """Narrow the shrink to the changes the failure actually implicates.

    The oracle returns more than a bit: a textual merge failure names the
    conflicting files, and a test failure names failing tests and files. When a
    merge outcome already names the changes it choked on, start there.
    """
    if result.merge is not None and not result.merge.ok and result.merge.order:
        implicated = frozenset(result.merge.order) & candidate
        if implicated and implicated != candidate:
            return implicated
    return None


def _next_candidate(
    all_changes: ChangeSet,
    state: SearchState,
    tried: Set[ChangeSet],
    weight: Optional[Callable[[ChangeId], float]],
    parents: Dependencies,
) -> Optional[ChangeSet]:
    """The cheapest not-yet-tried complement of a minimal hitting set.

    With stacked changes the complement is additionally narrowed to its largest
    downward-closed subset: dropping a change means dropping everything built on
    it, whether the hitting set said so or not.
    """
    for hitting_set in minimal_hitting_sets(state.conflicts, weight=weight):
        candidate = all_changes - hitting_set
        if parents:
            candidate = largest_closed_subset(candidate, parents)
        if candidate in tried:
            continue
        if any(candidate <= good for good in state.maximal_good_sets):
            continue
        return candidate
    return None


def _grow_within_known(
    candidate: ChangeSet,
    all_changes: ChangeSet,
    state: SearchState,
    parents: Dependencies,
) -> ChangeSet:
    """Add back anything no *known* conflict forbids, before calling it maximal.

    Costs no evaluations of its own: it only consults conflicts already found.
    Without it, upward-closing a hitting set over a stack can drop a change that
    nothing actually objected to, and the "maximal" set would be a set short.
    """
    grown = set(candidate)
    for extra in sorted(all_changes - candidate):
        trial = set(grown) | {extra} | set(
            a for a in _ancestors_within(extra, parents, all_changes)
        )
        if any(conflict <= trial for conflict in state.conflicts):
            continue
        grown = trial
    return frozenset(grown)


def _ancestors_within(
    change: ChangeId, parents: Dependencies, universe: ChangeSet
) -> ChangeSet:
    seen: Set[ChangeId] = set()
    current = parents.get(change)
    while current is not None and current in universe and current not in seen:
        seen.add(current)
        current = parents.get(current)
    return frozenset(seen)


def _keep_maximal(sets: Sequence[ChangeSet]) -> List[ChangeSet]:
    """Drop any set contained in another; keep a stable, readable order."""
    unique = {frozenset(s) for s in sets}
    maximal = [s for s in unique if not any(s < other for other in unique)]
    return sorted(maximal, key=lambda s: (-len(s), set_key(s)))


def independent_components(
    changes: Iterable[ChangeId],
    files_of: Callable[[ChangeId], Iterable[str]],
) -> List[ChangeSet]:
    """Split changes into groups that cannot possibly interact via files.

    Two changes touching disjoint file sets cannot conflict textually, and (as a
    working assumption worth stating out loud) rarely conflict semantically.
    Connected components of the file-overlap graph are therefore independent
    subproblems: solve each separately and combine the answers freely, which
    turns one ``2**n`` search into several much smaller ones.

    >>> files = {'a': ['x.py'], 'b': ['x.py'], 'c': ['y.py']}
    >>> [set_key(g) for g in independent_components(files, files.get)]
    [('a', 'b'), ('c',)]
    """
    changes = list(changes)
    file_sets: Dict[ChangeId, Set[str]] = {c: set(files_of(c) or ()) for c in changes}
    parent: Dict[ChangeId, ChangeId] = {c: c for c in changes}

    def find(x: ChangeId) -> ChangeId:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: ChangeId, y: ChangeId) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    by_file: Dict[str, List[ChangeId]] = {}
    for change, files in file_sets.items():
        for f in files:
            by_file.setdefault(f, []).append(change)
    for sharers in by_file.values():
        for other in sharers[1:]:
            union(sharers[0], other)

    groups: Dict[ChangeId, Set[ChangeId]] = {}
    for change in changes:
        groups.setdefault(find(change), set()).add(change)
    return sorted(
        (frozenset(g) for g in groups.values()), key=lambda s: (-len(s), set_key(s))
    )


def combine_components(
    per_component: Sequence[Sequence[ChangeSet]],
) -> List[ChangeSet]:
    """Cartesian-combine per-component maximal sets into global ones.

    >>> [set_key(s) for s in combine_components([[frozenset('a')], [frozenset('c')]])]
    [('a', 'c')]
    """
    combined = [frozenset()]
    for sets in per_component:
        combined = [acc | s for acc in combined for s in sets]
    return _keep_maximal(combined)
