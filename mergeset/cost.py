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
has ever been run, so :func:`cost_from_log` reads back data the package has been
storing all along.

**A cost model over CI timings has at least two regimes, because caching is what
makes CI affordable.** On a real run the base check — the empty set, evaluated
before anything else — took 51.2 s, while the nine candidate sets took 27.2 to
37.2 s. The base check is not a small candidate set: it is the first evaluation,
so it is the one that always pays the cold dependency install that every later
evaluation skips through a fingerprinted setup stage. It sits at the extreme of
the independent variable (size 0) *and* is the slowest run, which is exactly the
shape that dominates a linear fit: fit one line through both regimes and the
slope comes out **negative**, i.e. the model concludes that adding changes makes
validation faster. Budgets survive that, because the residual is enormous.
Ordering does not — and a wrong budget is visible where a wrong order is not.

Hence :meth:`MeasuredCost.central`: the slope is fitted on the body only, the
empty set is priced from its own regime instead of being extrapolated, and a
negative fitted slope degrades to the mean because adding a change cannot make
validation faster.

Two estimates, not one, because they answer different questions:

- :meth:`~MeasuredCost.estimate` — the central estimate, used for **ordering**.
- :meth:`~MeasuredCost.pessimistic` — plus the worst residual against that same
  model, used for **budget admission**, because overrunning a budget is a worse
  failure than deferring one evaluation. What it carries is the spread *within*
  a regime — an install that ran because the lockfile moved, a slow runner — and
  never a stand-in for a regime that should have been separated. The expensive
  regime is priced where it occurs and reserved explicitly instead; see
  ``mergeset.tiers._runs_allowed``.

Held as a hypothesis rather than a law: on the only data available the body was
remarkably **flat** — sd 3.1 s across set sizes 1 to 13, against a 27 s floor —
so set size may barely predict cost at all, and the slope may be modelling
noise. Nine points on one repository is not enough to drop it (a validator that
selects tests per change would genuinely have a slope), but it is enough to say
that the reserve is load-bearing and the fit is not yet demonstrated to be.
"""

from __future__ import annotations

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
    Union,
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

#: What one evaluation cost: total seconds, or a per-stage breakdown that is
#: summed. The mapping form exists so that recording per-stage durations
#: (i2mint/mergeset#17) lands as *data* rather than as a change to a published
#: signature — the regime this module infers today is one a breakdown states.
Seconds = Union[float, Mapping[str, float]]


def _total(seconds: Seconds) -> float:
    """Total seconds, whether given as a number or a per-stage breakdown.

    >>> _total(42.0)
    42.0
    >>> _total({'setup': 33.0, 'build': 9.0, 'test': 6.0})
    48.0
    """
    if isinstance(seconds, Mapping):
        return float(sum(seconds.values()))
    return float(seconds)


def _mean(values: Sequence[float]) -> float:
    """Arithmetic mean.

    Hand-rolled rather than ``statistics.fmean``: importing ``statistics`` pulls
    in ``decimal``, ``fractions`` and ``numbers``, about 10% of this package's
    cold import time, and this package has a CLI.

    >>> _mean([1.0, 2.0, 3.0])
    2.0
    """
    return sum(values) / len(values)


def _median(values: Sequence[float]) -> float:
    """Middle value, averaging the two middle ones for an even count.

    >>> _median([3.0, 1.0, 2.0])
    2.0
    >>> _median([1.0, 2.0, 3.0, 4.0])
    2.5
    """
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


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

    def observe(self, tier: str, subset: ChangeSet, seconds: Seconds) -> None:
        """Record what an evaluation cost, so the next estimate is better.

        ``seconds`` is a total, or a per-stage mapping that is summed.
        """
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

    A downward fit is not a discount, it is a broken model — adding a change
    cannot make validation faster — so it degrades to the mean rather than
    predicting that bigger sets are cheaper:

    >>> _fit([(0, 51.0), (10, 30.0)])
    (40.5, 0.0)
    """
    sizes = [float(n) for n, _ in points]
    seconds = [s for _, s in points]
    mean_size = _mean(sizes)
    mean_seconds = _mean(seconds)
    variance = sum((n - mean_size) ** 2 for n in sizes)
    if variance == 0:  # one distinct size: no slope is inferable
        return mean_seconds, 0.0
    slope = (
        sum((n - mean_size) * (s - mean_seconds) for n, s in zip(sizes, seconds))
        / variance
    )
    if slope < 0:
        return mean_seconds, 0.0
    return mean_seconds - slope * mean_size, slope


def _regimes(points: Sequence[Tuple[int, float]]):
    """Split observations into the base regime (size 0) and the body.

    The empty set is not a small candidate set. It is the base check — the one
    evaluation that always runs first and therefore always pays the cold path
    every later evaluation skips. See the module docstring.

    >>> _regimes([(0, 51.0), (6, 28.0), (9, 31.0)])
    ([(0, 51.0)], [(6, 28.0), (9, 31.0)])
    """
    base = [(n, s) for n, s in points if n == 0]
    body = [(n, s) for n, s in points if n > 0]
    return base, body


@dataclass
class MeasuredCost:
    """A per-tier cost model fitted to observations, backed by declarations.

    Args:
        declared: ``tier -> seconds``, used until that tier has been observed.
            This is how a tier nobody has ever run gets a sane price: the person
            adding it usually knows roughly what it costs.
        per_change: ``change id -> extra seconds`` this change adds to any
            evaluation containing it. The per-change half of the model, for the
            case where one candidate is known to be much heavier than the rest.
            Default: nothing, and the fitted slope carries the average
            per-change cost instead.
        unmeasured_seconds: Price of a tier with neither observations nor a
            declaration. See :data:`UNMEASURED_TIER_SECONDS`.

    >>> cost = MeasuredCost(declared={'e2e': 300.0})
    >>> cost.estimate('e2e', frozenset({'a'}))
    300.0
    >>> cost.is_measured('e2e')
    False
    >>> cost.observe('unit', frozenset({'a'}), 10.0)
    >>> cost.observe('unit', frozenset({'a', 'b', 'c'}), 20.0)
    >>> cost.observe('unit', frozenset({'a', 'b', 'c', 'd', 'e'}), 30.0)
    >>> cost.estimate('unit', frozenset({'a', 'b', 'c', 'd'}))
    25.0
    >>> cost.is_measured('unit')
    True

    An unknown tier is priced, not free — otherwise a cost-ordered scheduler
    would run it first, precisely because nobody has ever timed it:

    >>> cost.estimate('nobody-timed-this', frozenset({'a'}))
    60.0

    The base check is read from its own regime rather than extrapolated:

    >>> cold = MeasuredCost()
    >>> cold.observe('unit', frozenset(), 51.2)                  # base, cold
    >>> for n in range(1, 10):
    ...     cold.observe('unit', frozenset(range(n)), 30.0 + n / 10)
    >>> round(cold.estimate('unit', frozenset()), 1)             # its own regime
    51.2
    >>> round(cold.estimate('unit', frozenset(range(9))), 1)     # the body's
    30.9
    """

    declared: Mapping[str, float] = field(default_factory=dict)
    per_change: Mapping[ChangeId, float] = field(default_factory=dict)
    unmeasured_seconds: float = UNMEASURED_TIER_SECONDS
    #: ``tier -> [(set size, seconds)]``. Private, deliberately: the shape of one
    #: observation is exactly what recording per-stage durations would change
    #: (i2mint/mergeset#17), and a public attribute is an interface a PyPI
    #: release burns. The evidence behind an estimate is published through
    #: :meth:`summary`, which is a dict and can gain keys without breaking
    #: anyone.
    _observations: Dict[str, List[Tuple[int, float]]] = field(
        default_factory=dict, init=False, repr=False
    )

    def observe(self, tier: str, subset: ChangeSet, seconds: Seconds) -> None:
        """Record one real timing, as a total or a per-stage breakdown."""
        self._observations.setdefault(tier, []).append((len(subset), _total(seconds)))

    def is_measured(self, tier: str) -> bool:
        """True iff this tier's estimate comes from observations."""
        return bool(self._observations.get(tier))

    def runs(self, tier: str) -> int:
        """How many timings this tier's estimate rests on."""
        return len(self._observations.get(tier, ()))

    def forget(self, tier: str) -> None:
        """Drop this tier's observations, so a caller can re-ingest a log."""
        self._observations.pop(tier, None)

    def central(self, tier: str, size: int) -> float:
        """Seconds for a set of ``size`` at ``tier``, before per-change extras.

        The one place the model lives, so :meth:`estimate` and
        :meth:`pessimistic` cannot drift apart.

        Never below the fastest run ever observed for the tier. An evaluation
        that has never taken less than 27 s will not take 0 s, and a floor of
        zero is not merely inaccurate: it makes a budget check divide by nothing
        and conclude the tier is unlimited.
        """
        points = self._observations.get(tier)
        if points:
            base, body = _regimes(points)
            if size == 0 and base:
                return _mean([seconds for _, seconds in base])
            # Fit the slope on the regime every candidate set actually lives in.
            # Falling back to all points keeps a first run working, when the
            # base check may be the only thing measured.
            intercept, slope = _fit(body if len(body) >= 2 else points)
            floor = min(seconds for _, seconds in points)
            return max(floor, intercept + slope * size)
        if tier in self.declared:
            return float(self.declared[tier])
        return float(self.unmeasured_seconds)

    def estimate(self, tier: str, subset: ChangeSet) -> float:
        """Central estimate of what evaluating ``subset`` at ``tier`` will cost.

        >>> cost = MeasuredCost(declared={'unit': 10.0}, per_change={'x': -50.0})
        >>> cost.estimate('unit', frozenset({'x'}))
        0.0
        """
        extra = sum(self.per_change.get(cid, 0.0) for cid in subset)
        # Clamped *after* the surcharges, not before: a negative per-change
        # value would otherwise sail past a floor applied to the tier term alone
        # and produce a negative price.
        return max(0.0, self.central(tier, len(subset)) + extra)

    def pessimistic(self, tier: str, subset: ChangeSet) -> float:
        """Upper estimate: the central one plus the worst residual ever seen.

        With no observations there is no residual to add and this is the central
        estimate — the honest position, not an optimistic one: the declared or
        unmeasured number is already the only thing known.

        Note what this is *not* doing. The cold base check is priced by its own
        regime (see :meth:`central`), so it contributes no residual here. What
        this carries is the spread *within* a regime, which is the variance no
        candidate set predicts. The expensive regime is reserved explicitly by
        the scheduler instead of being smuggled in as a hedge.

        >>> cost = MeasuredCost()
        >>> cost.observe('unit', frozenset({'a'}), 45.0)
        >>> cost.observe('unit', frozenset({'a'}), 80.0)   # the lockfile moved
        >>> round(cost.estimate('unit', frozenset({'a'})), 1)
        62.5
        >>> round(cost.pessimistic('unit', frozenset({'a'})), 1)
        80.0
        """
        central = self.estimate(tier, subset)
        points = self._observations.get(tier)
        if not points:
            return central
        worst = max(seconds - self.central(tier, n) for n, seconds in points)
        return central + max(0.0, worst)

    def summary(self) -> Dict[str, dict]:
        """Per-tier view of the model, for a report to print.

        Says what the number is *and where it came from*, because an estimate
        with no provenance is indistinguishable from a magic constant. This is
        the published view of the evidence; the observation list itself is
        private, so its shape can change without breaking callers.
        """
        out: Dict[str, dict] = {}
        for tier in sorted(set(self._observations) | set(self.declared)):
            points = self._observations.get(tier) or []
            row = {
                "runs": len(points),
                "source": (
                    "measured"
                    if points
                    else ("declared" if tier in self.declared else "unknown")
                ),
            }
            if points:
                base, body = _regimes(points)
                seconds = [s for _, s in points]
                row["total_seconds"] = round(sum(seconds), 1)
                row["median_seconds"] = round(_median(seconds), 1)
                row["range_seconds"] = (round(min(seconds), 1), round(max(seconds), 1))
                # The regimes are reported separately, because the whole point
                # is that their means are not comparable.
                if base:
                    row["base_seconds"] = round(_mean([s for _, s in base]), 1)
                if body:
                    row["body_median_seconds"] = round(_median([s for _, s in body]), 1)
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
    not say — one log holds one tier's rows by construction
    (see :mod:`mergeset.tiers`).

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
