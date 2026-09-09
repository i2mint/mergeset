"""Tiered validation: a cheap oracle screens, an expensive one confirms.

``mergeset`` searches a **monotone** predicate — if a set fails, every superset
fails — which is what makes the search tractable at all. This module uses the
second half of that structure, which the package has so far left on the table:

    **The tiers are monotone in each other.** A set that fails a cheap tier
    fails overall, whatever the expensive tier would have said. So a cheap tier
    is a *sound filter*, and an expensive tier only ever needs to run on
    cheap-tier survivors.

That has a consequence worth stating as a lemma, because it is what makes an
unaffordable tier affordable:

    **Every maximal good set of the full oracle is contained in some maximal
    good set of the screen.** (If ``S`` passes everything then it passes the
    screen, so it sits inside some maximal screen-passing set.)

The maximal screen-passing sets are the **frontier**, and there are usually a
handful of them — four, on a real run of eighteen changes. Everything else the
search touches is *interior*: hitting-set probes and conflict shrinking, dozens
of evaluations, none of which can be the answer. So the expensive tier runs on
the frontier and never on the interior, and the question stops being "which of
2**18 subsets do I dare run browser tests on" and becomes "how few runs confirm
these four".

Mechanically that is one composed evaluator with two properties:

- **it short-circuits** — a cheap-tier failure answers the query without paying
  for the deep tier;
- **each tier keeps its own log.** A cheap-tier PASS is not evidence about the
  deep tier, so the two verdicts must not share a cache entry. This is D25 one
  level up: *verified* has to mean **verified at the tier you are claiming**,
  and a set confirmed only to the unit tier says so.

Two stages, and what each costs:

1. **Screen** — the ordinary search (:func:`mergeset.analyze`), with the cheap
   tier as its validator. Pays the whole interior at cheap-tier prices and
   returns the frontier plus every conflict it found.
2. **Confirm** — the same search again, one tier deeper, *seeded with those
   conflicts* so it starts almost finished. Its candidates are frontier sets;
   its interior is answered from the screen's log for free.

If a deep tier is unavailable (no container daemon today) or unaffordable,
stage 2 is skipped rather than degraded, and the answer is labelled with the
depth it actually reached. **A tier that did not run is not a tier that
passed.**
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import (
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from mergeset.analysis import Analysis, analyze
from mergeset.base import (
    Change,
    ChangeId,
    ChangeSet,
    Evaluation,
    MergesetError,
    ValidationOutcome,
    Verdict,
    set_key,
)
from mergeset.cost import CostModel, MeasuredCost
from mergeset.log import EvaluationLog, JsonlLines, StoreLines
from mergeset.oracle import git_oracle
from mergeset.solve import find_maximal_good_sets, minimal_hitting_sets, quickxplain
from mergeset.stacks import close_down, largest_closed_subset
from mergeset.storage import evaluation_log_path, slugify


@dataclass(frozen=True)
class Tier:
    """One rung of validation, from cheapest to dearest.

    Args:
        name: What this tier is (``unit``, ``integration``, ``e2e``). It names
            the tier's own evaluation log and appears in every claim the report
            makes, because "passed the unit tier" and "passed everything" are
            different facts.
        validate: ``worktree -> ValidationOutcome`` — the same contract as every
            validator in :mod:`mergeset.validation`, so
            :func:`~mergeset.validation.staged_validation` and friends drop
            straight in. A tier is *one* validator; the stages *within* it are
            that validator's own business.
        cost: Declared seconds per run, used until the tier has been timed.
            Worth setting for a tier nobody has run yet: it is what stops a
            cost-ordered scheduler treating an unmeasured tier as cheap.
        available: ``() -> bool`` — is the infrastructure this tier needs up?
            The honest reason a tier gets skipped is usually not budget but
            absence: no daemon, no display, no credentials. ``None`` means
            always available, which is the truth for a unit-test tier.

    >>> from mergeset.validation import merge_only_validation
    >>> tier = Tier('merge', merge_only_validation(), cost=0.5)
    >>> tier.name, tier.is_available()
    ('merge', True)
    >>> Tier('e2e', merge_only_validation(), available=lambda: False).is_available()
    False
    """

    name: str
    validate: Callable[[str], ValidationOutcome]
    cost: Optional[float] = None
    available: Optional[Callable[[], bool]] = None

    def is_available(self) -> bool:
        """Whether this tier can run right now."""
        return True if self.available is None else bool(self.available())


@dataclass(frozen=True)
class AnytimeAnswer:
    """The best answer so far, and how much better an answer could still be.

    ``bound`` is a genuine upper bound, not a hope. Every conflict — found at
    any tier, by any pre-oracle — refutes a real set, so the heaviest set that
    no known conflict forbids is the heaviest set that *could* still pass. Its
    weight is therefore an upper bound on the optimum, and ``gap`` is what is
    still unknown.

    ``gap <= 0`` together with full tier depth is a **certificate**: the
    heaviest set nothing refutes has itself been validated, so nothing better
    exists. That is a stopping rule rather than a budget running out.

    Attributes:
        best: Heaviest set validated so far, at ``best_tier``.
        best_weight: Its weight (the sum of its changes' weights).
        best_tier: Deepest tier that actually ran on ``best``; ``None`` when
            nothing has been validated yet.
        full_depth: True iff every tier ran on ``best``. When False, ``best`` is
            a partial claim however good ``gap`` looks.
        bound, bound_set: The upper bound and the set that realizes it.
        gap: ``bound - best_weight`` — what might still be being missed.
        optimal: ``gap <= 0 and full_depth``; nothing better exists.
        pending: ``(set, estimated seconds to confirm)`` for candidates not yet
            taken to full depth. The answer to "what would closing the gap
            cost".
        spent: Seconds spent, per tier.
    """

    best: Optional[ChangeSet]
    best_weight: float
    best_tier: Optional[str]
    full_depth: bool
    bound: float
    bound_set: Optional[ChangeSet]
    gap: float
    optimal: bool
    pending: Sequence[Tuple[ChangeSet, float]] = ()
    spent: Mapping[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        """One line a progress display or a report can print.

        >>> AnytimeAnswer(frozenset({'a'}), 1.0, 'unit', False, 2.0,
        ...               frozenset({'a', 'b'}), 1.0, False).summary()
        'best 1 change (weight 1.0, confirmed to tier `unit`); bound 2.0; gap 1.0'
        >>> AnytimeAnswer(frozenset({'a', 'b'}), 2.0, 'e2e', True, 2.0,
        ...               frozenset({'a', 'b'}), 0.0, True).summary()
        'best 2 changes (weight 2.0, all tiers); provably maximal'
        """
        if self.best is None:
            return f"nothing validated yet; bound {round(self.bound, 3)}"
        depth = (
            "all tiers" if self.full_depth else f"confirmed to tier `{self.best_tier}`"
        )
        n = len(self.best)
        head = (
            f"best {n} change{'s' if n != 1 else ''} "
            f"(weight {round(self.best_weight, 3)}, {depth})"
        )
        if self.optimal:
            return head + "; provably maximal"
        return head + f"; bound {round(self.bound, 3)}; gap {round(self.gap, 3)}"


@dataclass
class TieredAnalysis:
    """Result of a tiered run.

    ``analysis`` is an ordinary :class:`~mergeset.analysis.Analysis` whose
    ``maximal_sets``, ``unverified_sets`` and ``notes`` have been updated to the
    depth validation actually reached — so every existing report renders it
    unchanged and says the right thing about tiers.
    """

    tiers: List[Tier]
    analysis: Analysis
    logs: Dict[str, EvaluationLog]
    cost_model: CostModel
    #: How deep validation actually got, as a tier name.
    depth_reached: Optional[str] = None
    #: ``tier -> why it did not run``. Empty is the normal case.
    skipped: Dict[str, str] = field(default_factory=dict)
    #: Seconds spent per tier, measured from that tier's log.
    spent: Dict[str, float] = field(default_factory=dict)
    #: Evaluations actually performed, per tier.
    runs: Dict[str, int] = field(default_factory=dict)
    answer: Optional[AnytimeAnswer] = None
    #: Changes the caller required in the answer, if any.
    must_include: ChangeSet = frozenset()
    #: Heaviest validated set containing every change in ``must_include``.
    #: ``None`` when they cannot all be kept together. A second, differently
    #: constrained answer -- never a replacement for the first.
    best_including: Optional[ChangeSet] = None

    @property
    def maximal_sets(self) -> List[ChangeSet]:
        """The answer: maximal sets at the depth reached."""
        return list(self.analysis.maximal_sets)

    def verified_tier(self, subset: ChangeSet) -> Optional[str]:
        """The deepest tier that recorded an exact PASS for ``subset``.

        Inference across the monotone closure deliberately does not count. A
        passing *superset* is what makes a subset good by inference, and if such
        a superset existed it would be the answer instead — so for the purpose
        of "was this claim actually run", only an exact recorded PASS counts.
        D25's rule, applied per tier.
        """
        deepest = None
        for tier in self.tiers:
            log = self.logs.get(tier.name)
            exact = log.exact(frozenset(subset)) if log else None
            if exact is None or exact.verdict is not Verdict.PASS:
                return deepest
            deepest = tier.name
        return deepest


# --------------------------------------------------------------------------
# The lever: one evaluator per tier, chained and short-circuiting
# --------------------------------------------------------------------------


def chained_evaluate(evaluators: Sequence[Callable[[ChangeSet], Evaluation]]):
    """Compose per-tier evaluators into one, short-circuiting on the first failure.

    This is the lever. A set the cheap tier refutes never reaches the expensive
    one, so the search's interior — every hitting-set probe, every QuickXplain
    step — is paid at cheap-tier prices, and the expensive tier is spent only on
    sets that survived.

    >>> def cheap(s):
    ...     return Evaluation(s, Verdict.FAIL if 'bad' in s else Verdict.PASS)
    >>> deep_calls = []
    >>> def deep(s):
    ...     deep_calls.append(set_key(s))
    ...     return Evaluation(s, Verdict.PASS)
    >>> evaluate = chained_evaluate([cheap, deep])
    >>> evaluate(frozenset({'bad', 'x'})).verdict.value
    'fail'
    >>> deep_calls
    []
    >>> evaluate(frozenset({'x'})).verdict.value
    'pass'
    >>> deep_calls
    [('x',)]
    """
    if not evaluators:
        raise ValueError("chained_evaluate needs at least one evaluator")

    def evaluate(subset: ChangeSet) -> Evaluation:
        result = None
        for evaluate_at_tier in evaluators:
            result = evaluate_at_tier(subset)
            if result.verdict is not Verdict.PASS:
                return result
        return result

    return evaluate


def tier_lines(repo: str, tier: str, *, store=None):
    """The append-only lines object backing one tier's evaluation log.

    One log per tier, in the same artifact store as everything else, keyed by
    repository *and* tier. Sharing one log between tiers would make a cheap
    PASS answer an expensive question, which is the one thing this module
    exists to prevent.

    >>> backing = {}
    >>> lines = tier_lines('/x/proj/widget', 'e2e', store=backing)
    >>> lines.append({'a': 1}); list(backing)[0].endswith('.e2e.jsonl')
    True
    """
    if store is None:
        path = evaluation_log_path(repo)
        stem, ext = os.path.splitext(path)
        return JsonlLines(f"{stem}.{tier}{ext}")
    key = f"{slugify(os.path.abspath(os.path.expanduser(str(repo))))}.{tier}.jsonl"
    return StoreLines(store, key)


def _sync_costs(cost_model: CostModel, log: EvaluationLog, tier: str) -> float:
    """Re-read a tier's log into the cost model; return the seconds it records.

    The log has recorded the wall-clock of every evaluation since the package
    was written, so the price of a tier is measured rather than declared — this
    is what reads it back. Idempotent: the tier's observations are rebuilt, not
    appended to, so calling it after every stage is safe.
    """
    durations = [(e.subset, e.duration) for e in log if (e.duration or 0) > 0]
    if isinstance(cost_model, MeasuredCost):
        cost_model.observations[tier] = []
    for subset, seconds in durations:
        cost_model.observe(tier, subset, seconds)
    return sum(seconds for _, seconds in durations)


def _seed_conflicts(analysis: Analysis) -> List[ChangeSet]:
    """Every conflict the cheap phases established, in one list.

    The deep search is seeded with these so it starts at the frontier instead of
    rediscovering, at deep-tier prices, what a ``merge-tree`` call already knew.
    """
    seeds = [frozenset(c) for c in analysis.conflicts]
    seeds += [frozenset({a, b}) for a, b, _ in analysis.textual_conflicts]
    seeds += [frozenset({cid}) for cid in analysis.singleton_conflicts]
    return [s for s in seeds if s]


def _runs_allowed(
    cost_model: CostModel,
    tier: str,
    biggest: ChangeSet,
    *,
    budget_seconds: Optional[float],
    max_runs: Optional[int],
) -> Optional[int]:
    """How many runs of ``tier`` the budget admits; ``None`` means unlimited.

    Priced on the *largest* candidate with the *pessimistic* estimate, so the
    number is one the run can actually honour. An explicit ``max_runs`` wins,
    because a stated cap is a decision and a budget is an inference.

    >>> from mergeset.cost import MeasuredCost
    >>> cost = MeasuredCost(declared={'e2e': 300.0})
    >>> _runs_allowed(cost, 'e2e', frozenset({'a'}), budget_seconds=700, max_runs=None)
    2
    >>> _runs_allowed(cost, 'e2e', frozenset({'a'}), budget_seconds=100, max_runs=None)
    0
    >>> _runs_allowed(cost, 'e2e', frozenset({'a'}), budget_seconds=None, max_runs=None)
    """
    if max_runs is not None:
        return max_runs
    if budget_seconds is None:
        return None
    each = cost_model.pessimistic(tier, biggest)
    if each <= 0:
        return None
    return int(budget_seconds // each)


# --------------------------------------------------------------------------
# The anytime answer
# --------------------------------------------------------------------------


def anytime_answer(
    change_ids: Sequence[ChangeId],
    conflicts: Sequence[ChangeSet],
    *,
    weight: Callable[[ChangeId], float],
    verified: Sequence[Tuple[ChangeSet, Optional[str]]],
    tiers: Sequence[Tier],
    cost_model: Optional[CostModel] = None,
    remaining_tiers: Sequence[str] = (),
    spent: Optional[Mapping[str, float]] = None,
    pending_limit: int = 5,
) -> AnytimeAnswer:
    """The best validated set so far, plus a sound bound on what is being missed.

    Args:
        change_ids: The universe.
        conflicts: Every refuted set, from any tier or pre-oracle.
        weight: ``change id -> weight``; a set's weight is the sum of its own.
        verified: ``(set, deepest tier that ran on it)`` pairs.
        tiers: The tier chain, which is what "full depth" means.
        cost_model, remaining_tiers: Used to price ``pending``.
        spent: Seconds per tier, carried through for reporting.
        pending_limit: How many unconfirmed candidates to price.

    >>> tiers = [Tier('unit', lambda w: None), Tier('e2e', lambda w: None)]
    >>> answer = anytime_answer(
    ...     ['a', 'b', 'c'], [frozenset({'a', 'b'})], weight=lambda c: 1.0,
    ...     verified=[(frozenset({'a', 'c'}), 'e2e')], tiers=tiers)
    >>> answer.best_weight, answer.bound, answer.optimal
    (2.0, 2.0, True)

    Same conflicts, but the deep tier never ran. The bound is unchanged and the
    answer is explicitly *not* optimal, because a tier that did not run is not a
    tier that passed:

    >>> partial = anytime_answer(
    ...     ['a', 'b', 'c'], [frozenset({'a', 'b'})], weight=lambda c: 1.0,
    ...     verified=[(frozenset({'a', 'c'}), 'unit')], tiers=tiers)
    >>> partial.optimal, partial.full_depth, partial.best_tier
    (False, False, 'unit')
    """
    universe = frozenset(change_ids)

    def weight_of(subset: ChangeSet) -> float:
        return sum(weight(cid) for cid in subset)

    deepest = tiers[-1].name if tiers else None
    best_set: Optional[ChangeSet] = None
    best_weight = float("-inf")
    best_tier: Optional[str] = None
    for subset, tier_name in verified:
        if tier_name is None:
            continue
        candidate_weight = weight_of(subset)
        # Depth outranks weight: a set confirmed at the deepest tier is a better
        # *answer* than a heavier set confirmed only at the screen, however much
        # better the screen result looks on paper. Separating the tiers is
        # pointless if the ranking then ignores which one ran.
        rank = (tier_name == deepest, candidate_weight)
        best_rank = (best_tier == deepest, best_weight)
        if best_set is None or rank > best_rank:
            best_set = frozenset(subset)
            best_weight = candidate_weight
            best_tier = tier_name

    live = [frozenset(c) for c in conflicts if c]
    hitting = next(iter(minimal_hitting_sets(live, weight=weight)), frozenset())
    bound_set = universe - hitting
    bound = weight_of(bound_set)

    if best_set is None:
        best_weight = 0.0
    full_depth = best_tier is not None and best_tier == deepest
    gap = bound - best_weight
    optimal = full_depth and gap <= 0

    pending: List[Tuple[ChangeSet, float]] = []
    if cost_model is not None and remaining_tiers:
        confirmed = {frozenset(s) for s, t in verified if t == deepest}
        seen = set()
        for hitting_set in minimal_hitting_sets(live, weight=weight):
            candidate = universe - hitting_set
            if candidate in confirmed or candidate in seen:
                continue
            seen.add(candidate)
            price = sum(
                cost_model.pessimistic(tier, candidate) for tier in remaining_tiers
            )
            pending.append((candidate, round(price, 1)))
            if len(pending) >= pending_limit:
                break

    return AnytimeAnswer(
        best=best_set,
        best_weight=best_weight if best_set is not None else 0.0,
        best_tier=best_tier,
        full_depth=full_depth,
        bound=bound,
        bound_set=bound_set,
        gap=gap,
        optimal=optimal,
        pending=pending,
        spent=dict(spent or {}),
    )


# --------------------------------------------------------------------------
# The other frontier: the best plan that KEEPS a particular change
# --------------------------------------------------------------------------


def best_set_including(
    change_ids: Sequence[ChangeId],
    evaluate: Callable[[ChangeSet], Evaluation],
    *,
    must_include: Sequence[ChangeId],
    conflicts: Sequence[ChangeSet] = (),
    weight: Optional[Callable[[ChangeId], float]] = None,
    depends_on: Optional[Mapping[ChangeId, ChangeId]] = None,
    max_evaluations: Optional[int] = None,
    shrink: Callable[..., ChangeSet] = quickxplain,
) -> Tuple[Optional[ChangeSet], List[ChangeSet], int]:
    """The heaviest validated set that **contains** every change in ``must_include``.

    This is a different question from "the heaviest validated set", and on real
    data the two answers can be far apart. A change that must land — because it
    is the one the expensive tier exists for, or because someone has decided it
    ships — may conflict with several members of the unconstrained best plan; the
    best plan that keeps it is then not a superset of that plan, not a subset,
    and not reachable by adding anything to it. It is the complement of a minimal
    hitting set that *avoids* the required changes, which is what this
    enumerates.

    Args:
        change_ids: The universe.
        evaluate: The (chained, log-cached) oracle.
        must_include: Changes the answer must contain. With stacked changes the
            set is closed downward first, since keeping a change means keeping
            what it is built on.
        conflicts: Conflicts already known — the point of the exercise is to
            reuse everything the unconstrained search learned.
        weight: ``id -> weight``; candidates are proposed heaviest-first.
        depends_on: ``child -> parent`` for stacked changes.
        max_evaluations: Budget, in real (uncached) evaluations.
        shrink: Conflict-minimization strategy.

    Returns:
        ``(best set or None, the conflicts now known, evaluations spent)``.
        ``None`` means the required changes cannot all be kept: every way of
        resolving the known conflicts drops one of them.

    >>> from mergeset.base import Evaluation, Verdict
    >>> def oracle(subset):                      # 'h' conflicts with 'a' and 'b'
    ...     bad = {'h', 'a'} <= subset or {'h', 'b'} <= subset
    ...     return Evaluation(subset, Verdict.FAIL if bad else Verdict.PASS)
    >>> best, _, _ = best_set_including('abch', oracle, must_include=['h'])
    >>> set_key(best)
    ('c', 'h')

    Unconstrained, the answer would have been the three changes that exclude
    ``h`` — bigger, and not an answer to the question that was asked.
    """
    universe = frozenset(change_ids)
    parents = dict(depends_on or {})
    must = frozenset(must_include)
    if parents:
        must = close_down(must, parents)
    unknown = must - universe
    if unknown:
        raise ValueError(
            f"must_include names changes that are not candidates: {sorted(unknown)}"
        )
    weight = weight or (lambda _: 1.0)
    known = _minimal(list(conflicts))
    tried: set = set()
    spent = 0

    def counted(subset: ChangeSet) -> Evaluation:
        nonlocal spent
        result = evaluate(frozenset(subset))
        if not result.cached:
            spent += 1
        return result

    while max_evaluations is None or spent < max_evaluations:
        candidate = None
        for hitting_set in minimal_hitting_sets(known, weight=weight):
            proposal = universe - hitting_set
            if parents:
                proposal = largest_closed_subset(proposal, parents)
            # The one constraint that makes this a different search: a
            # resolution that drops a required change is not an answer to this
            # question, however good an answer it is to the unconstrained one.
            if not (must <= proposal) or proposal in tried:
                continue
            candidate = proposal
            break
        if candidate is None:
            return None, known, spent
        tried.add(candidate)
        result = counted(candidate)
        if result.verdict is Verdict.PASS:
            return candidate, known, spent
        if result.verdict is not Verdict.FAIL:
            return None, known, spent
        conflict = shrink(counted, sorted(candidate))
        known = _minimal(known + [conflict])
        if conflict <= must:
            # The required changes conflict with each other (or with the base).
            # No set containing them all can pass; say so rather than looping.
            return None, known, spent
    return None, known, spent


# --------------------------------------------------------------------------
# The facade
# --------------------------------------------------------------------------


def analyze_tiered(
    repo: str,
    changes: Sequence[Change],
    *,
    tiers: Sequence[Tier],
    cost_model: Optional[CostModel] = None,
    confirm_budget_seconds: Optional[float] = None,
    confirm_max_runs: Optional[int] = None,
    confirm_max_sets: Optional[int] = None,
    must_include: Sequence[ChangeId] = (),
    on_event: Optional[Callable[[str, dict], None]] = None,
    **analyze_kwargs,
) -> TieredAnalysis:
    """Screen with the cheap tier, confirm the frontier with the expensive ones.

    Args:
        repo, changes: As :func:`mergeset.analyze`.
        tiers: Ordered cheapest-first. The first is the **screen** and pays for
            the whole search interior; each later one confirms what its
            predecessor left standing. One tier reproduces today's behaviour
            exactly.
        cost_model: The price list — a seam. Default:
            :class:`~mergeset.cost.MeasuredCost` seeded from each tier's
            declared ``cost``, then fitted to the durations the tier's own
            evaluation log records. Measurements from one run price the next.
        confirm_budget_seconds: Wall-clock a deep tier may spend. Admission uses
            the model's *pessimistic* estimate, because overrunning a budget is
            worse than deferring one evaluation.
        confirm_max_runs: Hard cap on evaluations per deep tier. Takes
            precedence over the budget when both are given.
        confirm_max_sets: Stop a deep tier after this many confirmed maximal
            sets. ``1`` is "just tell me the single best plan, cheaply".
        must_include: Changes that must be in the answer. Answers a *different*
            question alongside the main one — "the best plan that keeps this" —
            and the two can be far apart when the required change conflicts with
            members of the unconstrained best plan. Reported as
            ``TieredAnalysis.best_including``; see :func:`best_set_including`.
        on_event: ``(event, payload)``. Adds ``tier``, ``tier_skipped`` and
            ``anytime`` on top of the events :func:`mergeset.analyze` emits, so
            a caller can display the best-so-far after every deep run.
        **analyze_kwargs: Everything else goes to :func:`mergeset.analyze`
            unchanged (``base``, ``decompose``, ``max_evaluations``, ...). Not
            ``validate`` and not ``log``: the tiers own both.

    Returns:
        A :class:`TieredAnalysis`.
    """
    tiers = list(tiers)
    if not tiers:
        raise ValueError(
            "analyze_tiered needs at least one tier. For a single validator pass "
            "tiers=[Tier('validate', my_validator)] -- or call analyze(), which "
            "is the same thing."
        )
    # `log_path` belongs in this list even though it names a path rather than a
    # log. One path cannot hold several tiers without collapsing them into the
    # one shared cache entry this design exists to prevent -- and since the
    # screen's log is passed explicitly below, `analyze` would ignore it in
    # silence. An argument that is quietly discarded is worse than one refused.
    for reserved in ("validate", "log", "log_path"):
        if reserved in analyze_kwargs:
            raise MergesetError(
                f"analyze_tiered owns `{reserved}`: each tier has its own "
                "validator and its own evaluation log, because a cheap-tier PASS "
                "is not evidence about an expensive tier and the two must not "
                "share a cache entry. Put a validator in a Tier; for the logs' "
                "location, pass `artifacts=` (the storage seam), which routes "
                f"every tier's log through one store. Do not pass {reserved}=."
            )
    names = [t.name for t in tiers]
    if len(set(names)) != len(names):
        raise ValueError(f"Tier names must be unique; got {names}.")

    emit = on_event or (lambda name, payload: None)
    cost_model = cost_model or MeasuredCost(
        declared={t.name: t.cost for t in tiers if t.cost is not None}
    )
    artifacts = analyze_kwargs.get("artifacts")
    store = artifacts["evaluations"] if artifacts else None
    logs = {t.name: EvaluationLog(tier_lines(repo, t.name, store=store)) for t in tiers}

    # --- stage 1: screen --------------------------------------------------
    screen = tiers[0]
    emit("tier", {"name": screen.name, "role": "screen"})
    analysis = analyze(
        repo,
        changes,
        validate=screen.validate,
        log=logs[screen.name],
        on_event=on_event,
        **analyze_kwargs,
    )
    result = TieredAnalysis(
        tiers=tiers,
        analysis=analysis,
        logs=logs,
        cost_model=cost_model,
        depth_reached=screen.name,
    )
    result.spent[screen.name] = _sync_costs(cost_model, logs[screen.name], screen.name)
    # Evaluations are counted from the tier's log, not from the search state:
    # a search resumed against a complete log runs nothing and would report
    # zero spend for work that really happened (i2mint/mergeset#16).
    result.runs[screen.name] = len(logs[screen.name])

    change_ids = [c.id for c in changes]
    universe = frozenset(change_ids)

    def weight_of_id(cid: ChangeId) -> float:
        return analysis.weights.get(cid, 1.0)

    conflicts = _seed_conflicts(analysis)

    def refresh_answer() -> AnytimeAnswer:
        remaining = [n for n in names if n not in result.spent]
        answer = anytime_answer(
            change_ids,
            conflicts,
            weight=weight_of_id,
            verified=[(s, result.verified_tier(s)) for s in analysis.maximal_sets],
            tiers=tiers,
            cost_model=cost_model,
            remaining_tiers=remaining,
            spent=result.spent,
        )
        result.answer = answer
        emit("anytime", {"summary": answer.summary(), "gap": answer.gap})
        return answer

    refresh_answer()

    # --- stages 2..n: confirm the frontier, one tier deeper each time -----
    evaluators = [
        _tier_evaluator(repo, analysis, changes, screen, logs[screen.name], emit)
    ]
    for tier in tiers[1:]:
        if not tier.is_available():
            _skip(
                result,
                analysis,
                tier,
                "the infrastructure it needs is not available",
                emit,
            )
            break
        allowance = _runs_allowed(
            cost_model,
            tier.name,
            universe,
            budget_seconds=confirm_budget_seconds,
            max_runs=confirm_max_runs,
        )
        if allowance is not None and allowance < 1:
            price = round(cost_model.pessimistic(tier.name, universe), 1)
            _skip(
                result,
                analysis,
                tier,
                f"the budget does not admit even one run (estimated {price}s each)",
                emit,
            )
            break
        evaluators.append(
            _tier_evaluator(repo, analysis, changes, tier, logs[tier.name], emit)
        )
        emit("tier", {"name": tier.name, "role": "confirm", "max_runs": allowance})
        state = find_maximal_good_sets(
            change_ids,
            chained_evaluate(evaluators),
            known_conflicts=conflicts,
            depends_on=analysis.stacks,
            weight=weight_of_id,
            max_evaluations=allowance,
            max_seconds=confirm_budget_seconds,
            max_sets=confirm_max_sets,
            on_event=on_event,
        )
        analysis.searches.append(state)
        conflicts = conflicts + list(state.conflicts)
        analysis.conflicts = _minimal(analysis.conflicts + state.conflicts)
        result.spent[tier.name] = _sync_costs(cost_model, logs[tier.name], tier.name)
        result.runs[tier.name] = len(logs[tier.name])
        if state.maximal_good_sets:
            analysis.maximal_sets = state.maximal_good_sets
        result.depth_reached = tier.name
        refresh_answer()
        if state.error:
            _skip(result, analysis, tier, f"it aborted: {state.error}", emit)
            break

    if must_include:
        result.must_include = frozenset(must_include)
        best, found, _ = best_set_including(
            change_ids,
            chained_evaluate(evaluators),
            must_include=must_include,
            conflicts=conflicts,
            weight=weight_of_id,
            depends_on=analysis.stacks,
            max_evaluations=confirm_max_runs,
        )
        result.best_including = best
        conflicts = _minimal(list(conflicts) + list(found))
        analysis.conflicts = _minimal(list(analysis.conflicts) + list(found))
        for tier_name in names:
            if tier_name in result.spent:
                result.spent[tier_name] = _sync_costs(
                    cost_model, logs[tier_name], tier_name
                )
                result.runs[tier_name] = len(logs[tier_name])
        kept = ", ".join(sorted(result.must_include))
        if best is None:
            analysis.notes.append(
                f"No validated set keeps {kept}: every way of resolving the known "
                "conflicts drops at least one of them. Landing it means fixing a "
                "conflict, not choosing a different subset."
            )
        else:
            analysis.notes.append(
                f"Best validated set that keeps {kept}: {len(best)} of "
                f"{len(change_ids)} changes ({', '.join(set_key(best))}). This is a "
                "different question from the maximal set above, and a smaller "
                "answer to it is not a worse answer."
            )

    _record_what_may_be_claimed(result, analysis, names, refresh_answer())
    return result


def _tier_evaluator(
    repo: str,
    analysis: Analysis,
    changes: Sequence[Change],
    tier: Tier,
    log: EvaluationLog,
    emit: Callable[[str, dict], None],
):
    """A log-cached evaluator for one tier: merge onto the base, then run the tier.

    Backed by the tier's *own* log, so a set the screen already decided is a
    cache hit at the screen and a real run only at the tier that has not seen it.
    """
    return log.caching(
        git_oracle(
            repo,
            analysis.base_sha,
            changes,
            validate=tier.validate,
            depends_on=analysis.stacks,
            on_event=lambda event, payload: emit(event, {**payload, "tier": tier.name}),
        )
    )


def _minimal(conflicts: Sequence[ChangeSet]) -> List[ChangeSet]:
    """Keep only minimal conflicts; a superset of a conflict says nothing new."""
    unique = {frozenset(c) for c in conflicts if c}
    return sorted(
        (c for c in unique if not any(other < c for other in unique)),
        key=lambda c: (len(c), set_key(c)),
    )


def _skip(
    result: TieredAnalysis,
    analysis: Analysis,
    tier: Tier,
    why: str,
    emit: Callable[[str, dict], None],
) -> None:
    result.skipped[tier.name] = why
    emit("tier_skipped", {"name": tier.name, "why": why})


def _record_what_may_be_claimed(
    result: TieredAnalysis,
    analysis: Analysis,
    names: Sequence[str],
    answer: AnytimeAnswer,
) -> None:
    """Write the tier depth into the Analysis, so every report says it.

    ``unverified_sets`` is the existing mechanism for "reported but never run as
    a whole" (D25). A set confirmed only to the screen is exactly that, one
    level up, so it goes in the same field and the same reports flag it.
    """
    deepest = result.depth_reached
    # `components_combined` is `analyze`'s record of whether the per-component
    # answers were *trusted* to combine (a merge-only validator declares that
    # they may). Where it trusted them, this layer must not be stricter than the
    # untiered path for the same validator -- that would report NOT VERIFIED on
    # every merge-only run. It only ever applies to the screen: every deeper tier
    # here is searched globally, so an exact PASS genuinely exists or does not.
    trusted = analysis.components_combined and deepest == result.tiers[0].name
    analysis.unverified_sets = (
        []
        if trusted
        else [s for s in analysis.maximal_sets if result.verified_tier(s) != deepest]
    )
    chain = " -> ".join(names)
    if deepest == names[-1]:
        analysis.notes.append(
            f"Validation was tiered ({chain}); every set below was confirmed at "
            f"the deepest tier, `{deepest}`."
        )
    else:
        missing = ", ".join(f"`{n}`" for n in names[names.index(deepest) + 1 :])
        analysis.notes.append(
            f"Validation was tiered ({chain}) but only reached `{deepest}`. The "
            f"sets below were NOT validated at {missing}, and a tier that did "
            f"not run is not a tier that passed."
        )
    for tier_name, why in result.skipped.items():
        analysis.notes.append(f"Tier `{tier_name}` did not run because {why}.")
    analysis.notes.append("Anytime status: " + answer.summary())
    if not answer.optimal and answer.pending:
        cheapest = min(price for _, price in answer.pending)
        analysis.notes.append(
            f"The gap is {round(answer.gap, 3)}. Closing it means confirming at "
            f"least one more candidate, the cheapest of which is estimated at "
            f"{cheapest}s at the remaining tiers."
        )
