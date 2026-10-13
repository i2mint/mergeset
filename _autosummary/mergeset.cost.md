# mergeset.cost

What an evaluation costs — per validation tier, and per change.

Until now `mergeset` treated every evaluation as costing the same: one suite
run. That is true only while there is one suite. As soon as validation is
*tiered* — a fast unit run, then a slow end-to-end run needing containers, a
database and a browser — the search is choosing between evaluations that differ
by two orders of magnitude, and it cannot choose well while it is told they are
the same.

So cost becomes an **input**, on the same footing as the changes and the base.
It is one keyword argument, and its default is measured rather than declared:
the evaluation log already records the wall-clock duration of everything that
has ever been run, so [`cost_from_log()`](#mergeset.cost.cost_from_log) reads back data the package has been
storing all along.

\*\*A cost model over CI timings has at least two regimes, because caching is what
makes CI affordable.\*\* On a real run the base check — the empty set, evaluated
before anything else — took 51.2 s, while the nine candidate sets took 27.2 to
37.2 s. The base check is not a small candidate set: it is the first evaluation,
so it is the one that always pays the cold dependency install that every later
evaluation skips through a fingerprinted setup stage. It sits at the extreme of
the independent variable (size 0) *and* is the slowest run, which is exactly the
shape that dominates a linear fit: fit one line through both regimes and the
slope comes out **negative**, i.e. the model concludes that adding changes makes
validation faster. Budgets survive that, because the residual is enormous.
Ordering does not — and a wrong budget is visible where a wrong order is not.

Hence [`MeasuredCost.central()`](#mergeset.cost.MeasuredCost.central): the slope is fitted on the body only, the
empty set is priced from its own regime instead of being extrapolated, and a
negative fitted slope degrades to the mean because adding a change cannot make
validation faster.

Two estimates, not one, because they answer different questions:

- [`estimate()`](#mergeset.cost.MeasuredCost.estimate) — the central estimate, used for **ordering**.
- [`pessimistic()`](#mergeset.cost.MeasuredCost.pessimistic) — plus the worst residual against that same
  model, used for **budget admission**, because overrunning a budget is a worse
  failure than deferring one evaluation. What it carries is the spread *within*
  a regime — an install that ran because the lockfile moved, a slow runner — and
  never a stand-in for a regime that should have been separated. The expensive
  regime is priced where it occurs and reserved explicitly instead; see
  `mergeset.tiers._runs_allowed`.

Held as a hypothesis rather than a law: on the only data available the body was
remarkably **flat** — sd 3.1 s across set sizes 1 to 13, against a 27 s floor —
so set size may barely predict cost at all, and the slope may be modelling
noise. Nine points on one repository is not enough to drop it (a validator that
selects tests per change would genuinely have a slope), but it is enough to say
that the reserve is load-bearing and the fit is not yet demonstrated to be.

### Module Attributes

| [`UNMEASURED_TIER_SECONDS`](#mergeset.cost.UNMEASURED_TIER_SECONDS)   | What one evaluation of a tier is assumed to cost when nothing is known about it — nothing measured, nothing declared.   |
|----------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| [`Seconds`](#mergeset.cost.Seconds)                   | total seconds, or a per-stage breakdown that is summed.                                                                 |

### Functions

| [`cost_from_log`](#mergeset.cost.cost_from_log)(log, \*, tier[, declared, ...])   | Seed a cost model from an existing evaluation log — the real default.   |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`set_cost`](#mergeset.cost.set_cost)(cost_model, tiers, subset, \*[, ...])  | What it costs to take `subset` all the way down `tiers`.                |

### Classes

| [`CostModel`](#mergeset.cost.CostModel)(\*args, \*\*kwargs)             | What the scheduler needs to know about price.                         |
|--------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`MeasuredCost`](#mergeset.cost.MeasuredCost)([declared, per_change, ...]) | A per-tier cost model fitted to observations, backed by declarations. |

### *class* mergeset.cost.CostModel(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

What the scheduler needs to know about price.

Any object with these four methods is a cost model: a table of declared
constants, a model fitted to the log, or something that queries a CI
provider’s historical timings.

#### estimate(tier, subset)

Central estimate, in seconds. Used to *order* candidate work.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### is_measured(tier)

Whether this tier’s estimate rests on observation or on a guess.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### observe(tier, subset, seconds)

Record what an evaluation cost, so the next estimate is better.

`seconds` is a total, or a per-stage mapping that is summed.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### pessimistic(tier, subset)

Upper estimate, in seconds. Used to *admit* work against a budget.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### *class* mergeset.cost.MeasuredCost(declared=<factory>, per_change=<factory>, unmeasured_seconds=60.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A per-tier cost model fitted to observations, backed by declarations.

* **Parameters:**
  * **declared** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `tier -> seconds`, used until that tier has been observed.
    This is how a tier nobody has ever run gets a sane price: the person
    adding it usually knows roughly what it costs.
  * **per_change** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `change id -> extra seconds` this change adds to any
    evaluation containing it. The per-change half of the model, for the
    case where one candidate is known to be much heavier than the rest.
    Default: nothing, and the fitted slope carries the average
    per-change cost instead.
  * **unmeasured_seconds** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Price of a tier with neither observations nor a
    declaration. See [`UNMEASURED_TIER_SECONDS`](#mergeset.cost.UNMEASURED_TIER_SECONDS).

```pycon
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
```

An unknown tier is priced, not free — otherwise a cost-ordered scheduler
would run it first, precisely because nobody has ever timed it:

```pycon
>>> cost.estimate('nobody-timed-this', frozenset({'a'}))
60.0
```

The base check is read from its own regime rather than extrapolated:

```pycon
>>> cold = MeasuredCost()
>>> cold.observe('unit', frozenset(), 51.2)                  # base, cold
>>> for n in range(1, 10):
...     cold.observe('unit', frozenset(range(n)), 30.0 + n / 10)
>>> round(cold.estimate('unit', frozenset()), 1)             # its own regime
51.2
>>> round(cold.estimate('unit', frozenset(range(9))), 1)     # the body's
30.9
```

#### central(tier, size)

Seconds for a set of `size` at `tier`, before per-change extras.

The one place the model lives, so [`estimate()`](#mergeset.cost.MeasuredCost.estimate) and
[`pessimistic()`](#mergeset.cost.MeasuredCost.pessimistic) cannot drift apart.

Never below the fastest run ever observed for the tier. An evaluation
that has never taken less than 27 s will not take 0 s, and a floor of
zero is not merely inaccurate: it makes a budget check divide by nothing
and conclude the tier is unlimited.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### estimate(tier, subset)

Central estimate of what evaluating `subset` at `tier` will cost.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

```pycon
>>> cost = MeasuredCost(declared={'unit': 10.0}, per_change={'x': -50.0})
>>> cost.estimate('unit', frozenset({'x'}))
0.0
```

#### forget(tier)

Drop this tier’s observations, so a caller can re-ingest a log.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### is_measured(tier)

True iff this tier’s estimate comes from observations.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### observe(tier, subset, seconds)

Record one real timing, as a total or a per-stage breakdown.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### pessimistic(tier, subset)

Upper estimate: the central one plus the worst residual ever seen.

With no observations there is no residual to add and this is the central
estimate — the honest position, not an optimistic one: the declared or
unmeasured number is already the only thing known.

Note what this is *not* doing. The cold base check is priced by its own
regime (see [`central()`](#mergeset.cost.MeasuredCost.central)), so it contributes no residual here. What
this carries is the spread *within* a regime, which is the variance no
candidate set predicts. The expensive regime is reserved explicitly by
the scheduler instead of being smuggled in as a hedge.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

```pycon
>>> cost = MeasuredCost()
>>> cost.observe('unit', frozenset({'a'}), 45.0)
>>> cost.observe('unit', frozenset({'a'}), 80.0)   # the lockfile moved
>>> round(cost.estimate('unit', frozenset({'a'})), 1)
62.5
>>> round(cost.pessimistic('unit', frozenset({'a'})), 1)
80.0
```

#### runs(tier)

How many timings this tier’s estimate rests on.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### summary()

Per-tier view of the model, for a report to print.

Says what the number is *and where it came from*, because an estimate
with no provenance is indistinguishable from a magic constant. This is
the published view of the evidence; the observation list itself is
private, so its shape can change without breaking callers.

* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### mergeset.cost.Seconds

total seconds, or a per-stage breakdown that is
summed. The mapping form exists so that recording per-stage durations
(i2mint/mergeset#17) lands as *data* rather than as a change to a published
signature — the regime this module infers today is one a breakdown states.

* **Type:**
  What one evaluation cost

alias of [`float`](https://docs.python.org/3/builtins/functions.html#float) | [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### mergeset.cost.UNMEASURED_TIER_SECONDS *= 60.0*

What one evaluation of a tier is assumed to cost when nothing is known about
it — nothing measured, nothing declared. It is the first run of a brand new
tier, and the honest answer is “we do not know yet”.

One minute is chosen to be *wrong in the safe direction*: large enough that a
cost-ordered scheduler puts an unknown tier after every tier it has actually
timed, small enough that a first run still gets scheduled at all. `inf`
would be safer still and would mean no new tier ever runs a first time, which
is not a cost model but a refusal. Override it with one keyword argument.

### mergeset.cost.cost_from_log(log, , tier, declared=None, per_change=None, unmeasured_seconds=60.0)

Seed a cost model from an existing evaluation log — the real default.

Every row of the log already carries `subset` and `duration`, so the
price of the tier that produced that log is not a thing anyone needs to
declare: it has been measured, repeatedly, and thrown away. This reads it
back.

`tier` names which tier those rows belong to, because the log itself does
not say — one log holds one tier’s rows by construction
(see [`mergeset.tiers`](mergeset.tiers.md#module-mergeset.tiers)).

* **Return type:**
  [`MeasuredCost`](#mergeset.cost.MeasuredCost)

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> rows = [Evaluation(frozenset({'a'}), Verdict.PASS, duration=40.0),
...         Evaluation(frozenset({'a', 'b', 'c'}), Verdict.FAIL, duration=60.0)]
>>> cost = cost_from_log(rows, tier='unit')
>>> cost.estimate('unit', frozenset({'a', 'b'}))
50.0
```

### mergeset.cost.set_cost(cost_model, tiers, subset, , pessimistic=False)

What it costs to take `subset` all the way down `tiers`.

The tiers run in order and every one of them runs, so the price of a full
verdict is their sum — which is exactly what makes a cheap first tier worth
having: most sets never reach the second term.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

```pycon
>>> cost = MeasuredCost(declared={'unit': 45.0, 'e2e': 300.0})
>>> set_cost(cost, ['unit', 'e2e'], frozenset({'a'}))
345.0
```
