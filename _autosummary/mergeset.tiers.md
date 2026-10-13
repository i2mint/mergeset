# mergeset.tiers

Tiered validation: a cheap oracle screens, an expensive one confirms.

`mergeset` searches a **monotone** predicate — if a set fails, every superset
fails — which is what makes the search tractable at all. This module uses the
second half of that structure, which the package has so far left on the table:

> **The tiers are monotone in each other.** A set that fails a cheap tier
> fails overall, whatever the expensive tier would have said. So a cheap tier
> is a *sound filter*, and an expensive tier only ever needs to run on
> cheap-tier survivors.

That has a consequence worth stating as a lemma, because it is what makes an
unaffordable tier affordable:

> \*\*Every maximal good set of the full oracle is contained in some maximal
> good set of the screen.\*\* (If `S` passes everything then it passes the
> screen, so it sits inside some maximal screen-passing set.)

The maximal screen-passing sets are the **frontier**, and there are usually a
handful of them — four, on a real run of eighteen changes. Everything else the
search touches is *interior*: hitting-set probes and conflict shrinking, dozens
of evaluations, none of which can be the answer. So the question stops being
“which of 2\*\*18 subsets do I dare run browser tests on” and becomes “how few runs
confirm these four”.

The claim is **not** that the expensive tier never touches the interior — that
would be false, and measuring it says so. A conflict visible *only* to the deep
tier has to be shrunk at deep prices, and QuickXplain’s `O(k log(n/k))` queries
for a conflict of size `k` are interior by construction. What holds is the
useful half: a set the screen refutes is never paid for at depth, so the interior
the *screen* explores is free, and deep spending is bounded by the frontier plus
the shrinking that genuine deep-only conflicts force. On eight branches with one
deep-only conflict that is 7 deep runs against 10 screen runs; with no deep-only
conflict it is the frontier and nothing else.

Mechanically that is one composed evaluator with two properties:

- **it short-circuits** — a cheap-tier failure answers the query without paying
  for the deep tier;
- **each tier keeps its own log.** A cheap-tier PASS is not evidence about the
  deep tier, so the two verdicts must not share a cache entry. This is D25 one
  level up: *verified* has to mean **verified at the tier you are claiming**,
  and a set confirmed only to the unit tier says so.

Two stages, and what each costs:

1. **Screen** — the ordinary search ([`mergeset.analyze()`](mergeset.md#mergeset.analyze)), with the cheap
   tier as its validator. Pays the whole interior at cheap-tier prices and
   returns the frontier plus every conflict it found.
2. **Confirm** — the same search again, one tier deeper, \*seeded with those
   conflicts\* so it starts almost finished. Its candidates are frontier sets;
   its interior is answered from the screen’s log for free.

If a deep tier is unavailable (no container daemon today) or unaffordable,
stage 2 is skipped rather than degraded, and the answer is labelled with the
depth it actually reached. \*\*A tier that did not run is not a tier that
passed.\*\*

### Functions

| [`analyze_tiered`](#mergeset.tiers.analyze_tiered)(repo, changes, \*, tiers[, ...])   | Screen with the cheap tier, confirm the frontier with the expensive ones.    |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`anytime_answer`](#mergeset.tiers.anytime_answer)(change_ids, conflicts, \*, ...)    | The best validated set so far, plus a sound bound on what is being missed.   |
| [`best_set_including`](#mergeset.tiers.best_set_including)(change_ids, evaluate, \*, ...) | The heaviest validated set that **contains** every change in `must_include`. |
| [`chained_evaluate`](#mergeset.tiers.chained_evaluate)(evaluators)                      | Compose per-tier evaluators into one, short-circuiting on the first failure. |
| [`tier_key`](#mergeset.tiers.tier_key)(tier)                                    | The key-safe form of a tier name.                                            |
| [`tier_lines`](#mergeset.tiers.tier_lines)(repo, tier, \*[, store])               | The append-only lines object backing one tier's evaluation log.              |

### Classes

| [`AnytimeAnswer`](#mergeset.tiers.AnytimeAnswer)(best, best_weight, best_tier, ...)   | The best answer so far, and how much better an answer could still be.   |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`Tier`](#mergeset.tiers.Tier)(name, validate[, cost, available])            | One rung of validation, from cheapest to dearest.                       |
| [`TieredAnalysis`](#mergeset.tiers.TieredAnalysis)(tiers, analysis, logs, cost_model)  | Result of a tiered run.                                                 |

### *class* mergeset.tiers.AnytimeAnswer(best, best_weight, best_tier, full_depth, bound, bound_set, gap, optimal, pending=(), spent=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The best answer so far, and how much better an answer could still be.

`bound` is a genuine upper bound, not a hope. Every conflict — found at
any tier, by any pre-oracle — refutes a real set, so the heaviest set that
no known conflict forbids is the heaviest set that *could* still pass. Its
weight is therefore an upper bound on the optimum, and `gap` is what is
still unknown.

`gap <= 0` together with full tier depth is a **certificate**: the
heaviest set nothing refutes has itself been validated, so nothing better
exists. That is a stopping rule rather than a budget running out.

#### best

Heaviest set validated so far, at `best_tier`.

#### best_weight

Its weight (the sum of its changes’ weights).

#### best_tier

Deepest tier that actually ran on `best`; `None` when
nothing has been validated yet.

#### full_depth

True iff every tier ran on `best`. When False, `best` is
a partial claim however good `gap` looks.

### bound, bound_set

The upper bound and the set that realizes it.

#### gap

`bound - best_weight` — what might still be being missed.

#### optimal

`gap <= 0 and full_depth`; nothing better exists.

#### pending

`(set, estimated seconds to confirm)` for candidates not yet
taken to full depth. The answer to “what would closing the gap
cost”.

#### spent

Seconds spent, per tier.

#### summary()

One line a progress display or a report can print.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> AnytimeAnswer(frozenset({'a'}), 1.0, 'unit', False, 2.0,
...               frozenset({'a', 'b'}), 1.0, False).summary()
'best 1 change (weight 1.0, confirmed to tier `unit`); bound 2.0; gap 1.0'
>>> AnytimeAnswer(frozenset({'a', 'b'}), 2.0, 'e2e', True, 2.0,
...               frozenset({'a', 'b'}), 0.0, True).summary()
'best 2 changes (weight 2.0, all tiers); provably maximal'
```

### *class* mergeset.tiers.Tier(name, validate, cost=None, available=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One rung of validation, from cheapest to dearest.

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What this tier is (`unit`, `integration`, `e2e`). It names
    the tier’s own evaluation log and appears in every claim the report
    makes, because “passed the unit tier” and “passed everything” are
    different facts.
  * **validate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.md#mergeset.base.ValidationOutcome)]) – `worktree -> ValidationOutcome` — the same contract as every
    validator in [`mergeset.validation`](mergeset.validation.md#module-mergeset.validation), so
    [`staged_validation()`](mergeset.validation.md#mergeset.validation.staged_validation) and friends drop
    straight in. A tier is *one* validator; the stages *within* it are
    that validator’s own business.
  * **cost** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Declared seconds per run, used until the tier has been timed.
    Worth setting for a tier nobody has run yet: it is what stops a
    cost-ordered scheduler treating an unmeasured tier as cheap.
  * **available** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]) – `() -> bool` — is the infrastructure this tier needs up?
    The honest reason a tier gets skipped is usually not budget but
    absence: no daemon, no display, no credentials. `None` means
    always available, which is the truth for a unit-test tier.

```pycon
>>> from mergeset.validation import merge_only_validation
>>> tier = Tier('merge', merge_only_validation(), cost=0.5)
>>> tier.name, tier.is_available()
('merge', True)
>>> Tier('e2e', merge_only_validation(), available=lambda: False).is_available()
False
```

#### is_available()

Whether this tier can run right now.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### *class* mergeset.tiers.TieredAnalysis(tiers, analysis, logs, cost_model, depth_reached=None, skipped=<factory>, spent=<factory>, runs=<factory>, answer=None, must_include=frozenset({}), best_including=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of a tiered run.

`analysis` is an ordinary [`Analysis`](mergeset.analysis.md#mergeset.analysis.Analysis) whose
`maximal_sets`, `unverified_sets` and `notes` have been updated to the
depth validation actually reached — so every existing report renders it
unchanged and says the right thing about tiers.

#### best_including *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

Heaviest validated set containing every change in `must_include`.
`None` when they cannot all be kept together. A second, differently
constrained answer – never a replacement for the first.

#### depth_reached *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

How deep validation actually got, as a tier name.

#### *property* maximal_sets *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

maximal sets at the depth reached.

* **Type:**
  The answer

#### must_include *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)* *= frozenset({})*

Changes the caller required in the answer, if any.

#### runs *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [int](https://docs.python.org/3/builtins/functions.html#int)]*

Evaluations actually performed, per tier.

#### skipped *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

`tier -> why it did not run`. Empty is the normal case.

#### spent *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

Seconds spent per tier, measured from that tier’s log.

#### verified_tier(subset)

The deepest tier that recorded an exact PASS for `subset`.

Inference across the monotone closure deliberately does not count. A
passing *superset* is what makes a subset good by inference, and if such
a superset existed it would be the answer instead — so for the purpose
of “was this claim actually run”, only an exact recorded PASS counts.
D25’s rule, applied per tier.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.tiers.analyze_tiered(repo, changes, , tiers, cost_model=None, confirm_budget_seconds=None, confirm_max_runs=None, confirm_max_sets=None, must_include=(), on_event=None, \*\*analyze_kwargs)

Screen with the cheap tier, confirm the frontier with the expensive ones.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – As [`mergeset.analyze()`](mergeset.md#mergeset.analyze).
  * **changes** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Change`](mergeset.base.md#mergeset.base.Change)]) – As [`mergeset.analyze()`](mergeset.md#mergeset.analyze).
  * **tiers** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Tier`](#mergeset.tiers.Tier)]) – Ordered cheapest-first. The first is the **screen** and pays for
    the whole search interior; each later one confirms what its
    predecessor left standing. One tier reproduces today’s behaviour
    exactly.
  * **cost_model** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`CostModel`](mergeset.cost.md#mergeset.cost.CostModel)]) – The price list — a seam. Default:
    [`MeasuredCost`](mergeset.cost.md#mergeset.cost.MeasuredCost) seeded from each tier’s
    declared `cost`, then fitted to the durations the tier’s own
    evaluation log records. Measurements from one run price the next.
  * **confirm_budget_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Wall-clock a deep tier may spend. Admission uses
    the model’s *pessimistic* estimate, because overrunning a budget is
    worse than deferring one evaluation.
  * **confirm_max_runs** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Hard cap on evaluations per deep tier. Takes
    precedence over the budget when both are given.
  * **confirm_max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Stop a deep tier after this many confirmed maximal
    sets. `1` is “just tell me the single best plan, cheaply”.
  * **must_include** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Changes that must be in the answer. Answers a *different*
    question alongside the main one — “the best plan that keeps this” —
    and the two can be far apart when the required change conflicts with
    members of the unconstrained best plan. Reported as
    `TieredAnalysis.best_including`; see [`best_set_including()`](#mergeset.tiers.best_set_including).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – `(event, payload)`. Adds `tier`, `tier_skipped` and
    `anytime` on top of the events [`mergeset.analyze()`](mergeset.md#mergeset.analyze) emits, so
    a caller can display the best-so-far after every deep run.
  * **\*\*analyze_kwargs** – Everything else goes to [`mergeset.analyze()`](mergeset.md#mergeset.analyze)
    unchanged (`base`, `decompose`, `max_evaluations`, …). Not
    `validate` and not `log`: the tiers own both.
* **Return type:**
  [`TieredAnalysis`](#mergeset.tiers.TieredAnalysis)
* **Returns:**
  A [`TieredAnalysis`](#mergeset.tiers.TieredAnalysis).

### mergeset.tiers.anytime_answer(change_ids, conflicts, , weight, verified, tiers, cost_model=None, remaining_tiers=(), depends_on=None, spent=None, pending_limit=5, bound_search_limit=64)

The best validated set so far, plus a sound bound on what is being missed.

* **Parameters:**
  * **change_ids** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The universe.
  * **conflicts** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Every refuted set, from any tier or pre-oracle.
  * **weight** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `change id -> weight`; a set’s weight is the sum of its own.
  * **verified** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `(set, deepest tier that ran on it)` pairs.
  * **tiers** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Tier`](#mergeset.tiers.Tier)]) – The tier chain, which is what “full depth” means.
  * **cost_model** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`CostModel`](mergeset.cost.md#mergeset.cost.CostModel)]) – Used to price `pending`.
  * **remaining_tiers** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Used to price `pending`.
  * **depends_on** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `child -> parent` for stacked changes. Without it the
    bound names sets that could never land — a child without its parent
    — so `optimal` never becomes true however much is validated, and
    `pending` prices candidates nobody can run.
  * **bound_search_limit** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many minimal hitting sets to consider when
    tightening the bound under stack closure. Closure can only shrink a
    complement, so it breaks the weight ordering the enumeration relies
    on; past this many, the loose-but-sound unclosed bound is used.
  * **spent** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Seconds per tier, carried through for reporting.
  * **pending_limit** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many unconfirmed candidates to price.
* **Return type:**
  [`AnytimeAnswer`](#mergeset.tiers.AnytimeAnswer)

```pycon
>>> tiers = [Tier('unit', lambda w: None), Tier('e2e', lambda w: None)]
>>> answer = anytime_answer(
...     ['a', 'b', 'c'], [frozenset({'a', 'b'})], weight=lambda c: 1.0,
...     verified=[(frozenset({'a', 'c'}), 'e2e')], tiers=tiers)
>>> answer.best_weight, answer.bound, answer.optimal
(2.0, 2.0, True)
```

Same conflicts, but the deep tier never ran. The bound is unchanged and the
answer is explicitly *not* optimal, because a tier that did not run is not a
tier that passed:

```pycon
>>> partial = anytime_answer(
...     ['a', 'b', 'c'], [frozenset({'a', 'b'})], weight=lambda c: 1.0,
...     verified=[(frozenset({'a', 'c'}), 'unit')], tiers=tiers)
>>> partial.optimal, partial.full_depth, partial.best_tier
(False, False, 'unit')
```

### mergeset.tiers.best_set_including(change_ids, evaluate, \*, must_include, conflicts=(), weight=None, depends_on=None, max_evaluations=None, shrink=<function quickxplain>)

The heaviest validated set that **contains** every change in `must_include`.

This is a different question from “the heaviest validated set”, and on real
data the two answers can be far apart. A change that must land — because it
is the one the expensive tier exists for, or because someone has decided it
ships — may conflict with several members of the unconstrained best plan; the
best plan that keeps it is then not a superset of that plan, not a subset,
and not reachable by adding anything to it. It is the complement of a minimal
hitting set that *avoids* the required changes, which is what this
enumerates.

* **Parameters:**
  * **change_ids** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The universe.
  * **evaluate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.md#mergeset.base.Evaluation)]) – The (chained, log-cached) oracle.
  * **must_include** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Changes the answer must contain. With stacked changes the
    set is closed downward first, since keeping a change means keeping
    what it is built on.
  * **conflicts** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflicts already known — the point of the exercise is to
    reuse everything the unconstrained search learned.
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `id -> weight`; candidates are proposed heaviest-first.
  * **depends_on** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `child -> parent` for stacked changes.
  * **max_evaluations** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budget, in real (uncached) evaluations.
  * **shrink** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflict-minimization strategy.
* **Return type:**
  [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`int`](https://docs.python.org/3/builtins/functions.html#int)]
* **Returns:**
  `(best set or None, the conflicts now known, evaluations spent)`.
  `None` means the required changes cannot all be kept: every way of
  resolving the known conflicts drops one of them.

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> def oracle(subset):                      # 'h' conflicts with 'a' and 'b'
...     bad = {'h', 'a'} <= subset or {'h', 'b'} <= subset
...     return Evaluation(subset, Verdict.FAIL if bad else Verdict.PASS)
>>> best, _, _ = best_set_including('abch', oracle, must_include=['h'])
>>> set_key(best)
('c', 'h')
```

Unconstrained, the answer would have been the three changes that exclude
`h` — bigger, and not an answer to the question that was asked.

### mergeset.tiers.chained_evaluate(evaluators)

Compose per-tier evaluators into one, short-circuiting on the first failure.

This is the lever. A set the cheap tier refutes never reaches the expensive
one, so the search’s interior — every hitting-set probe, every QuickXplain
step — is paid at cheap-tier prices, and the expensive tier is spent only on
sets that survived.

```pycon
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
```

### mergeset.tiers.tier_key(tier)

The key-safe form of a tier name.

The repository half of a log key has always been slugified; the tier half
was interpolated raw, and that is not merely untidy. `e2e` and `E2E` are
two tier names and one file on macOS and Windows — a cheap-tier PASS
answering an expensive-tier question, on the default filesystem of two of
three platforms. `a/b` and `x/../y` reach outside the store entirely.

Case is folded rather than preserved because the collision is the point: two
names differing only in case must be *rejected* as duplicates, never
silently merged into one log. A name that had to be changed at all carries a
short digest of the original, so two different unsafe names cannot be
flattened onto one key either.

`mergeset.storage.slugify` is not reused here: it always appends a digest,
which is right for a long filesystem path and wrong for a name a person
typed and will read back in a report.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> tier_key('e2e'), tier_key('E2E')
('e2e', 'e2e')
>>> tier_key('a/b') == tier_key('x/../y')
False
>>> '/' in tier_key('a/b')
False
```

### mergeset.tiers.tier_lines(repo, tier, , store=None)

The append-only lines object backing one tier’s evaluation log.

One log per tier, in the same artifact store as everything else, keyed by
repository *and* tier. Sharing one log between tiers would make a cheap
PASS answer an expensive question, which is the one thing this module
exists to prevent — so both halves of the key are slugified.

```pycon
>>> backing = {}
>>> lines = tier_lines('/x/proj/widget', 'e2e', store=backing)
>>> lines.append({'a': 1}); list(backing)[0].endswith('.e2e.jsonl')
True
```
