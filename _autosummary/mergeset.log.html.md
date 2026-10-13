# mergeset.log

The evaluation log: append-only JSONL, and the single source of truth.

Every expensive evaluation is written here once and never re-run. The log also
carries the *monotone closure*: because good sets are (approximately) downward
closed, a passing set marks all of its subsets known-good, and a failing set
marks all of its supersets known-bad. That closure is computed lazily from the
stored rows rather than materialized, so the file stays small and honest.

Monotonicity is a strong prior, not a law: a change may contain the fix that
makes another change work, and flaky tests break it outright. Violations are
detected and reported ([`EvaluationLog.monotonicity_violations()`](#mergeset.log.EvaluationLog.monotonicity_violations)) instead of
being silently trusted.

A row is an answer about *commits*, not about ids. Once the log is pinned
([`EvaluationLog.pin()`](#mergeset.log.EvaluationLog.pin)) to the base and the head of each change in play,
only rows evaluated against those same commits count — rows about an older head
of a rewritten branch are kept on disk and in [`EvaluationLog.rows`](#mergeset.log.EvaluationLog.rows), and
simply not matched (i2mint/mergeset#23).

### Functions

| [`sets_evaluated`](#mergeset.log.sets_evaluated)(log)   | Yield `(sorted ids, verdict)` for every row — handy for reports.   |
|------------------------------------------------------------------------|--------------------------------------------------------------------|

### Classes

| [`EvaluationLog`](#mergeset.log.EvaluationLog)([store, pins, trust_unpinned])   | Append-only record of evaluations, plus the monotone closure over it.                                 |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [`JsonlLines`](#mergeset.log.JsonlLines)(path)                               | Append-only sequence of JSON objects backed by one file.                                              |
| [`Known`](#mergeset.log.Known)(verdict[, exact, witness])               | What the log already knows about a set, without re-evaluating it.                                     |
| [`MemoryLines`](#mergeset.log.MemoryLines)([iterable])                        | In-memory stand-in for [`JsonlLines`](#mergeset.log.JsonlLines) (tests, dry runs). |
| [`Pins`](#mergeset.log.Pins)(base, heads)                              | The commits a question is about: the base, and each change's head sha.                                |
| [`StoreLines`](#mergeset.log.StoreLines)(store, key)                         | Lines backed by one key of a `MutableMapping` — the non-file backend.                                 |

### *class* mergeset.log.EvaluationLog(store=None, , pins=None, trust_unpinned=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Append-only record of evaluations, plus the monotone closure over it.

* **Parameters:**
  * **store** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Persistence seam. A path (str/PathLike) is wrapped in
    [`JsonlLines`](#mergeset.log.JsonlLines); pass [`StoreLines`](#mergeset.log.StoreLines) to put the log in an
    artifact store (S3 and friends), or [`MemoryLines`](#mergeset.log.MemoryLines) for an
    ephemeral log. With no argument at all the log goes to the artifact
    store’s `evaluations/adhoc.jsonl` — never the working directory.
  * **pins** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Pins`](#mergeset.log.Pins)]) – The commits the questions are about (see [`Pins`](#mergeset.log.Pins) and
    [`pin()`](#mergeset.log.EvaluationLog.pin)). Unpinned, every row counts, as before pinning existed;
    [`mergeset.analyze()`](mergeset.html.md#mergeset.analyze) always pins.
  * **trust_unpinned** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Let rows that record no commits at all (written before
    i2mint/mergeset#23, or by an unpinned log) count as matches once the
    log is pinned. Off by default, because such a row may be about a head
    that has since moved — which is the defect pinning exists to close.
    Turn it on only when you know the heads have not moved since those
    rows were written; it is the migration path for an old log.

```pycon
>>> log = EvaluationLog(MemoryLines())
>>> from mergeset.base import Evaluation, Verdict
>>> _ = log.record(Evaluation(frozenset({'a', 'b'}), Verdict.PASS))
>>> bool(log.known(frozenset({'a'})))          # subset of a passing set
True
>>> log.known(frozenset({'a'})).verdict.value
'pass'
>>> _ = log.record(Evaluation(frozenset({'c', 'd'}), Verdict.FAIL))
>>> log.known(frozenset({'a', 'c', 'd'})).verdict.value   # superset of a failing set
'fail'
>>> log.known(frozenset({'a', 'c'})).verdict is None
True
```

#### caching(evaluate)

Wrap `evaluate` so known sets are answered from the log.

The returned callable is what the solver should be handed: it never
spends a real evaluation on a set the log can already decide.

#### exact(subset)

The most recent evaluation of exactly this set, if any.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]

#### *property* failing *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

Sets recorded as bad, smallest first (smallest are the most useful).

#### known(subset)

What we know about `subset` without evaluating it.

Exact hits win; otherwise the monotone closure decides, preferring the
cheapest witness (the largest passing superset, the smallest failing
subset).

* **Return type:**
  [`Known`](#mergeset.log.Known)

#### maximal_passing_sets()

Recorded passing sets with no recorded passing proper superset.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

#### minimal_failing_sets()

Recorded failing sets with no recorded failing proper subset.

These are the *conflicts* the solver hits. They are minimal with respect
to what has been observed, which is not necessarily globally minimal —
the solver shrinks them further with QuickXplain as it goes.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

#### monotonicity_violations()

`(good, bad)` pairs where a *subset* of a good set was seen failing.

A non-empty result means the downward-closure assumption broke here:
a flaky test, a non-deterministic build, or a change that *fixes*
another. Reported, never silently smoothed over.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]]

#### *property* passing *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

Sets recorded as good, largest first.

#### pin(, base, heads)

Scope *this* log to `base` and these heads; returns `self`.

[`pinned()`](#mergeset.log.EvaluationLog.pinned) is the same without changing this object.

From here on, reading ([`known()`](#mergeset.log.EvaluationLog.known), [`exact()`](#mergeset.log.EvaluationLog.exact), the closure,
iteration, `len`) sees only rows evaluated against these commits, and
[`record()`](#mergeset.log.EvaluationLog.record) stamps new rows with them. Nothing is removed: the other
rows stay in the store and in [`rows`](#mergeset.log.EvaluationLog.rows), and are reported by
[`stale`](#mergeset.log.EvaluationLog.stale) and [`unpinned`](#mergeset.log.EvaluationLog.unpinned).

* **Return type:**
  [`EvaluationLog`](#mergeset.log.EvaluationLog)

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> log = EvaluationLog(MemoryLines()).pin(base='B', heads={'a': 'A1'})
>>> _ = log.record(Evaluation(frozenset('a'), Verdict.PASS))
>>> log.known(frozenset('a')).verdict.value
'pass'
>>> _ = log.pin(base='B', heads={'a': 'A2'})   # branch a was rewritten
>>> log.known(frozenset('a')).verdict is None, len(log.rows), len(log.stale)
(True, 1, 1)
```

#### pinned(, base, heads, trust_unpinned=None)

A view of this log scoped to `base` and these heads.

Same store, same rows; this log itself is left as it was, so a caller
that hands one log to two analyses keeps its own view of it.

* **Return type:**
  [`EvaluationLog`](#mergeset.log.EvaluationLog)

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> log = EvaluationLog(MemoryLines())
>>> view = log.pinned(base='B', heads={'a': 'A1'})
>>> _ = view.record(Evaluation(frozenset('a'), Verdict.PASS))
>>> log.pins is None, len(log), len(view)
(True, 1, 1)
>>> len(log.pinned(base='B', heads={'a': 'A2'}))
0
```

#### record(evaluation)

Append `evaluation` and return it.

`at` is stamped if absent, and so are the pinned commits: a row that
does not say what it was run against cannot be told apart from one
about a branch that has since been rewritten.

* **Return type:**
  [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)

#### *property* rows *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Evaluation](mergeset.base.html.md#mergeset.base.Evaluation)]*

Every row in the log, matching the pins or not, in log order.

#### *property* stale *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Evaluation](mergeset.base.html.md#mergeset.base.Evaluation)]*

Rows evaluated against other commits than the pinned ones.

Not wrong — about a different question — so kept, and not matched.

#### *property* trust_unpinned *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether rows recording no commits count once the log is pinned.

#### *property* unpinned *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Evaluation](mergeset.base.html.md#mergeset.base.Evaluation)]*

Rows recording no commits that a pinned log is not counting.

All of them by default; with `trust_unpinned`, only those holding a
change that is not in play. Empty when the log is unpinned.

### *class* mergeset.log.JsonlLines(path)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Append-only sequence of JSON objects backed by one file.

The default persistence seam of [`EvaluationLog`](#mergeset.log.EvaluationLog). Any object with
`append(jdict)` and `__iter__() -> Iterable[jdict]` can replace it (an
in-memory list, a `dol` store, a database table).

```pycon
>>> import tempfile, os
>>> path = os.path.join(tempfile.mkdtemp(), 'x.jsonl')
>>> lines = JsonlLines(path)
>>> lines.append({'a': 1}); lines.append({'a': 2})
>>> [d['a'] for d in lines]
[1, 2]
```

#### append(jdict)

Append one record, flushing immediately (crash-safe enough).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* mergeset.log.Known(verdict, exact=None, witness=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What the log already knows about a set, without re-evaluating it.

#### exact *: [Evaluation](mergeset.base.html.md#mergeset.base.Evaluation) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

The recorded evaluation, when the set itself was evaluated.

#### witness *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

The witness set that implied the verdict, when it was inferred.

### *class* mergeset.log.MemoryLines(iterable=(),)

Bases: [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

In-memory stand-in for [`JsonlLines`](#mergeset.log.JsonlLines) (tests, dry runs).

#### append(jdict)

Append object to the end of the list.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* mergeset.log.Pins(base, heads)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The commits a question is about: the base, and each change’s head sha.

A row *matches* when it was merged onto the same base and every change it
holds is in play with the same head. A row holding a change that is not in
play does not match: its head for that change is unchecked, and such a row
would otherwise surface as an “established” set recommending a change
nobody asked about, or as a monotonicity violation between two heads of it.

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> pins = Pins('B', {'a': 'A1', 'b': 'B1'})
>>> row = Evaluation(frozenset('ab'), Verdict.PASS,
...                  base_sha='B', heads={'a': 'A1', 'b': 'B1'})
>>> pins.matches(row)
True
>>> pins.matches(replace(row, heads={'a': 'A0', 'b': 'B1'}))  # a rewritten
False
>>> pins.matches(replace(row, base_sha='B0'))                 # base moved
False
>>> Pins('B', {'a': 'A1'}).matches(row)          # b is not in play
False
```

#### matches(evaluation)

True iff `evaluation` was run against these commits.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### stamp(evaluation)

`evaluation` pinned to these commits (unless it already is).

* **Return type:**
  [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)

### *class* mergeset.log.StoreLines(store, key)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Lines backed by one key of a `MutableMapping` — the non-file backend.

[`JsonlLines`](#mergeset.log.JsonlLines) is the right thing over a filesystem: `open(..., 'a')`
is a true append. An object store has no append, so this reads, concatenates
and writes back. That is honest about the cost rather than pretending, and it
is what lets the evaluation log — the source of truth — reach S3 through the
same seam as everything else.

A missing key reads as empty rather than raising, so a first run works.

```pycon
>>> backing = {}
>>> lines = StoreLines(backing, 'run.jsonl')
>>> list(lines)
[]
>>> lines.append({'a': 1}); lines.append({'a': 2})
>>> [d['a'] for d in lines]
[1, 2]
>>> backing['run.jsonl']
'{"a": 1}\n{"a": 2}\n'
```

#### append(jdict)

Append one record by rewriting the value (no append primitive here).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### mergeset.log.sets_evaluated(log)

Yield `(sorted ids, verdict)` for every row — handy for reports.

* **Return type:**
  [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]
