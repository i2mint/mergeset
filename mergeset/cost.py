"""What an evaluation costs — per validation tier, and per change.

Until now ``mergeset`` treated every evaluation as costing the same: one suite
run. That is true only while there is one suite. As soon as validation is
*tiered* — a fast unit run, then a slow end-to-end run needing containers, a
database and a browser — the search is choosing between evaluations that differ
by two orders of magnitude, and it cannot choose well while it is told they are
the same.

So cost becomes an **input**, on the same footing as the changes and the base.
It is one keyword argument, and its default is measured rather than declared:
the evaluation log already records the wall-clock duration of everything that
has ever been run, so :func:`cost_from_log` fits a per-tier model to data the
package has been storing all along.

The model is deliberately the simplest thing that is not a lie::

    seconds(tier, subset) = intercept(tier) + slope(tier) * |subset| + per-change extras

fitted by ordinary least squares on the ``(len(subset), duration)`` pairs the
log holds for that tier. Two numbers per tier, from data you already have, and
it answers both questions the scheduler asks: *"which of these is cheaper"* and
*"will this fit in the budget"*.

Two estimates, not one, because they are used for different decisions:

- :meth:`~MeasuredCost.estimate` — the central estimate. Used for **ordering**:
  which frontier set to confirm first.
- :meth:`~MeasuredCost.pessimistic` — the estimate plus the worst residual seen.
  Used for **budget checks**, because overrunning a budget is a worse failure
  than deferring one evaluation. On a real project the two differ a lot: a
  fingerprinted dependency install that is skipped on a cache hit and paid on a
  miss is the single largest term in a JS validation tier, and nothing in the
  subset predicts which will happen.

An unmeasured, undeclared tier is not free and must not look free; see
:data:`UNMEASURED_TIER_SECONDS`.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

from mergeset.base import ChangeId, ChangeSet

#: What one evaluation of a tier is assumed to cost when nothing is known about
#: it — nothing measured, nothing declared. It is the first run of a brand new
#: tier, and the honest answer is "we do not know yet".
#:
#: One minute is chosen to be *wrong in the safe direction*: large enough that a
#: cost-ordered scheduler puts an unknown tier after every tier it has actually
#: timed, small enough that a first run still gets scheduled at all. ``inf``
#: would be safer still and would mean no new tier ever runs a first time, which
#: is not a cost model but a refusal. Override it with one keyword argument.
UNMEASURED_TIER_SECONDS = 60.0


@runtime_checkable
class CostModel(Protocol):
    """What the scheduler needs to know about price.

    Any object with these four methods is a cost model: a table of declared
    constants, a model fitted to the log, or something that queries a CI
    provider's historical timings.
    """

    def estimate(self, tier: str, subset: ChangeSet) -> float:
        """Central estimate, in seconds. Used to *order* candidate work."""
        ...

    def pessimistic(self, tier: str, subset: ChangeSet) -> float:
        """Upper estimate, in seconds. Used to *admit* work against a budget."""
        ...

    def observe(self, tier: str, subset: ChangeSet, seconds: float) -> None:
        """Record what an evaluation actually cost, so the next estimate is better."""
        ...

    def is_measured(self, tier: str) -> bool:
        """Whether this tier's estimate rests on observation or on a guess."""
        ...


def _fit(points: Sequence[Tuple[int, float]]) -> Tuple[float, float]:
    """Least-squares ``(intercept, slope)`` of seconds against set size.

    Falls back gracefully as data thins out: with a single distinct size there
    is no slope to fit, so the whole cost is attributed to the intercept — which
    is the right reading of "every run I have seen took about this long".

    >>> _fit([(0, 10.0), (2, 20.0), (4, 30.0)])
    (10.0, 5.0)
    >>> _fit([(3, 42.0), (3, 44.0)])
    (43.0, 0.0)
    """
    sizes = [float(n) for n, _ in points]
    seconds = [s for _, s in points]
    mean_size = statistics.fmean(sizes)
    mean_seconds = statistics.fmean(seconds)
    variance = sum((n - mean_size) ** 2 for n in sizes)
    if variance == 0:  # one distinct size: no slope is inferable
        return mean_seconds, 0.0
    slope = (
        sum((n - mean_size) * (s - mean_seconds) for n, s in zip(sizes, seconds))
        / variance
    )
    return mean_seconds - slope * mean_size, slope


@dataclass
class MeasuredCost:
    """A per-tier cost model fitted to observations, backed by declarations.

    Args:
        declared: ``tier -> seconds``, used until that tier has been observed.
            This is how a tier nobody has ever run gets a sane price: the person
            adding it usually knows roughly what it costs.
        per_change: ``change id -> extra seconds`` this change adds to any
            evaluation containing it. The per-change half of the model, for the
            case where one candidate is known to be much heavier than the rest
            (a change that adds a slow test module, say). Default: nothing, and
            the fitted slope carries the average per-change cost instead.
        unmeasured_seconds: Price of a tier with neither observations nor a
            declaration. See :data:`UNMEASURED_TIER_SECONDS`.

    >>> cost = MeasuredCost(declared={'e2e': 300.0})
    >>> cost.estimate('e2e', frozenset({'a'}))
    300.0
    >>> cost.is_measured('e2e')
    False
    >>> cost.observe('unit', frozenset(), 10.0)
    >>> cost.observe('unit', frozenset({'a', 'b'}), 20.0)
    >>> cost.estimate('unit', frozenset({'a', 'b', 'c', 'd'}))
    30.0
    >>> cost.is_measured('unit')
    True

    An unknown tier is priced, not free — otherwise a cost-ordered scheduler
    would run it first, precisely because nobody has ever timed it:

    >>> cost.estimate('nobody-timed-this', frozenset({'a'}))
    60.0
    """

    declared: Mapping[str, float] = field(default_factory=dict)
    per_change: Mapping[ChangeId, float] = field(default_factory=dict)
    unmeasured_seconds: float = UNMEASURED_TIER_SECONDS
    #: ``tier -> [(set size, seconds)]``. Public because it is the evidence: a
    #: report that shows an estimate should be able to show what it rests on.
    observations: Dict[str, List[Tuple[int, float]]] = field(default_factory=dict)

    def observe(self, tier: str, subset: ChangeSet, seconds: float) -> None:
        """Record one real timing."""
        self.observations.setdefault(tier, []).append((len(subset), float(seconds)))

    def is_measured(self, tier: str) -> bool:
        """True iff this tier's estimate comes from observations of *this* run."""
        return bool(self.observations.get(tier))

    def estimate(self, tier: str, subset: ChangeSet) -> float:
        """Central estimate of what evaluating ``subset`` at ``tier`` will cost."""
        extra = sum(self.per_change.get(cid, 0.0) for cid in subset)
        points = self.observations.get(tier)
        if points:
            intercept, slope = _fit(points)
            return max(0.0, intercept + slope * len(subset)) + extra
        if tier in self.declared:
            return float(self.declared[tier]) + extra
        return float(self.unmeasured_seconds) + extra

    def pessimistic(self, tier: str, subset: ChangeSet) -> float:
        """Upper estimate: the central one plus the worst residual ever seen.

        With no observations there is no residual to add and this is the central
        estimate — which is the honest position, not an optimistic one: the
        declared or unmeasured number is already the only thing known.

        >>> cost = MeasuredCost()
        >>> cost.observe('unit', frozenset({'a'}), 45.0)
        >>> cost.observe('unit', frozenset({'a'}), 80.0)   # cold: the install ran
        >>> round(cost.estimate('unit', frozenset({'a'})), 1)
        62.5
        >>> round(cost.pessimistic('unit', frozenset({'a'})), 1)
        80.0
        """
        central = self.estimate(tier, subset)
        points = self.observations.get(tier)
        if not points:
            return central
        intercept, slope = _fit(points)
        worst = max(seconds - (intercept + slope * n) for n, seconds in points)
        return central + max(0.0, worst)

    def summary(self) -> Dict[str, dict]:
        """Per-tier view of the model, for a report to print.

        Says what the number is *and where it came from*, because an estimate
        with no provenance is indistinguishable from a magic constant.
        """
        out: Dict[str, dict] = {}
        for tier in sorted(set(self.observations) | set(self.declared)):
            points = self.observations.get(tier) or []
            row = {
                "runs": len(points),
                "source": (
                    "measured"
                    if points
                    else ("declared" if tier in self.declared else "unknown")
                ),
            }
            if points:
                seconds = [s for _, s in points]
                row["total_seconds"] = round(sum(seconds), 1)
                row["median_seconds"] = round(statistics.median(seconds), 1)
                row["range_seconds"] = (round(min(seconds), 1), round(max(seconds), 1))
            elif tier in self.declared:
                row["declared_seconds"] = float(self.declared[tier])
            out[tier] = row
        return out


def cost_from_log(
    log: Iterable,
    *,
    tier: str,
    declared: Optional[Mapping[str, float]] = None,
    per_change: Optional[Mapping[ChangeId, float]] = None,
    unmeasured_seconds: float = UNMEASURED_TIER_SECONDS,
) -> MeasuredCost:
    """Seed a cost model from an existing evaluation log — the real default.

    Every row of the log already carries ``subset`` and ``duration``, so the
    price of the tier that produced that log is not a thing anyone needs to
    declare: it has been measured, repeatedly, and thrown away. This reads it
    back.

    ``tier`` names which tier those rows belong to, because the log itself does
    not say — it predates tiers, and one log holds one tier's rows by
    construction (see :mod:`mergeset.tiers`).

    Args:
        log: Anything iterating :class:`~mergeset.base.Evaluation` objects — an
            :class:`~mergeset.log.EvaluationLog` is the obvious one.
        tier: The tier those rows measured.
        declared, per_change, unmeasured_seconds: Passed to :class:`MeasuredCost`.

    >>> from mergeset.base import Evaluation, Verdict
    >>> rows = [Evaluation(frozenset({'a'}), Verdict.PASS, duration=40.0),
    ...         Evaluation(frozenset({'a', 'b', 'c'}), Verdict.FAIL, duration=60.0)]
    >>> cost = cost_from_log(rows, tier='unit')
    >>> cost.estimate('unit', frozenset({'a', 'b'}))
    50.0
    """
    model = MeasuredCost(
        declared=dict(declared or {}),
        per_change=dict(per_change or {}),
        unmeasured_seconds=unmeasured_seconds,
    )
    for evaluation in log:
        duration = getattr(evaluation, "duration", 0.0) or 0.0
        if duration > 0:
            model.observe(tier, evaluation.subset, duration)
    return model


def set_cost(
    cost_model: CostModel,
    tiers: Sequence[str],
    subset: ChangeSet,
    *,
    pessimistic: bool = False,
) -> float:
    """What it costs to take ``subset`` all the way down ``tiers``.

    The tiers run in order and every one of them runs, so the price of a full
    verdict is their sum — which is exactly what makes a cheap first tier worth
    having: most sets never reach the second term.

    >>> cost = MeasuredCost(declared={'unit': 45.0, 'e2e': 300.0})
    >>> set_cost(cost, ['unit', 'e2e'], frozenset({'a'}))
    345.0
    """
    return sum(
        (cost_model.pessimistic if pessimistic else cost_model.estimate)(tier, subset)
        for tier in tiers
    )
