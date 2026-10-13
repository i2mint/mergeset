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

### Functions

| [`sets_evaluated`](#mergeset.log.sets_evaluated)(log)   | Yield `(sorted ids, verdict)` for every row — handy for reports.   |
|------------------------------------------------------------------------|--------------------------------------------------------------------|

### Classes

| [`EvaluationLog`](#mergeset.log.EvaluationLog)([store])           | Append-only record of evaluations, plus the monotone closure over it.                                 |
|-----------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [`JsonlLines`](#mergeset.log.JsonlLines)(path)                 | Append-only sequence of JSON objects backed by one file.                                              |
| [`Known`](#mergeset.log.Known)(verdict[, exact, witness]) | What the log already knows about a set, without re-evaluating it.                                     |
| [`MemoryLines`](#mergeset.log.MemoryLines)([iterable])          | In-memory stand-in for [`JsonlLines`](#mergeset.log.JsonlLines) (tests, dry runs). |
| [`StoreLines`](#mergeset.log.StoreLines)(store, key)           | Lines backed by one key of a `MutableMapping` — the non-file backend.                                 |

### *class* mergeset.log.EvaluationLog(store=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Append-only record of evaluations, plus the monotone closure over it.

* **Parameters:**
  **store** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Persistence seam. A path (str/PathLike) is wrapped in
  [`JsonlLines`](#mergeset.log.JsonlLines); pass [`StoreLines`](#mergeset.log.StoreLines) to put the log in an
  artifact store (S3 and friends), or [`MemoryLines`](#mergeset.log.MemoryLines) for an
  ephemeral log. With no argument at all the log goes to the artifact
  store’s `evaluations/adhoc.jsonl` — never the working directory.

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
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Evaluation`](mergeset.base.md#mergeset.base.Evaluation)]

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

#### record(evaluation)

Append `evaluation` (stamping `at` if absent) and return it.

* **Return type:**
  [`Evaluation`](mergeset.base.md#mergeset.base.Evaluation)

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

#### exact *: [Evaluation](mergeset.base.md#mergeset.base.Evaluation) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

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
