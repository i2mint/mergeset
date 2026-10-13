# mergeset.base

Core data structures and vocabulary of `mergeset`.

The unit of work is a **change**: a commit range `base..head`. Branches, pull
requests and explicit commit lists are merely *sources* that produce changes
(see [`mergeset.sources`](mergeset.sources.md#module-mergeset.sources)). Everything downstream — the evaluation log, the
solver, the report — speaks only of changes, identified by their string `id`.

A **change set** is a `frozenset` of change ids. Sets are the atoms the solver
reasons about; they are serialized as sorted lists so the JSONL log is stable
and diffable.

### Module Attributes

| [`MergeFn`](#mergeset.base.MergeFn)    | (changes to merge, in order) -> outcome + a tree to validate.   |
|-------------------------------------------------------------|-----------------------------------------------------------------|
| [`ValidateFn`](#mergeset.base.ValidateFn) | (path to a merged worktree) -> outcome.                         |

### Functions

| [`change_set`](#mergeset.base.change_set)(ids)   | Normalize any iterable of change ids into a `frozenset`.   |
|--------------------------------------------------------------------|------------------------------------------------------------|
| [`set_key`](#mergeset.base.set_key)(ids)      | A stable, hashable, JSON-friendly key for a change set.    |

### Classes

| [`Change`](#mergeset.base.Change)(id, head, base[, source, weight, meta])   | One candidate change: everything between `base` and `head`.   |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| [`Evaluation`](#mergeset.base.Evaluation)(subset, verdict[, stage, merge, ...]) | One row of the evaluation log — the single source of truth.   |
| [`Evaluator`](#mergeset.base.Evaluator)(\*args, \*\*kwargs)                    | Callable that decides whether a change set is good.           |
| [`MergeOutcome`](#mergeset.base.MergeOutcome)(ok[, reason, ...])                  | Result of merging a change set onto its base.                 |
| [`Stage`](#mergeset.base.Stage)(\*values)                                  | Where an evaluation ended.                                    |
| [`StageRun`](#mergeset.base.StageRun)(name[, duration, returncode, skipped])  | What one stage of a staged validation did, and what it cost.  |
| [`ValidationOutcome`](#mergeset.base.ValidationOutcome)(ok[, failing_tests, ...])      | Result of validating a merged tree.                           |
| [`Verdict`](#mergeset.base.Verdict)(\*values)                                | Outcome of evaluating a change set.                           |

### Exceptions

| [`CapabilityError`](#mergeset.base.CapabilityError)   | A required external capability is missing; the message says how to fix it.   |
|--------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`MergesetError`](#mergeset.base.MergesetError)     | Base class for errors this package raises deliberately.                      |

### *exception* mergeset.base.CapabilityError

Bases: [`MergesetError`](#mergeset.base.MergesetError)

A required external capability is missing; the message says how to fix it.

### *class* mergeset.base.Change(id, head, base, source='branch', weight=None, meta=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One candidate change: everything between `base` and `head`.

* **Parameters:**
  * **id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Short stable identifier, used everywhere else (log, report, CLI).
  * **head** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Commit-ish holding the change (branch name, sha, PR head).
  * **base** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Commit-ish the change is measured against.
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Which source produced it (`'branch'`, `'pr'`, `'commit'`).
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Cost of *dropping* this change. The solver drops the cheapest
    changes it can when it must drop something, so a high weight means
    “keep me”. `None` means “let the weighting policy decide”.
  * **meta** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – Source-specific extras (PR number, author, CI status, draft flag…).

```pycon
>>> c = Change(id='fix-a', head='origin/fix-a', base='origin/main')
>>> c.id, c.source
('fix-a', 'branch')
```

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.base.Change.to_jdict).

* **Return type:**
  [`Change`](#mergeset.base.Change)

#### to_jdict()

JSON-able view of the change.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### with_weight(weight)

A copy of this change carrying `weight`.

* **Return type:**
  [`Change`](#mergeset.base.Change)

### *class* mergeset.base.Evaluation(subset, verdict, stage=None, merge=None, validation=None, duration=0.0, at=None, note='', base_sha=None, heads=<factory>, cached=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the evaluation log — the single source of truth.

Everything else (conflict set, known-good/known-bad closure, merge plan,
reports) is *derived* from a sequence of these and is re-derivable.

A row is about the commits that were actually merged, not about the ids:
`base_sha` and `heads` (change id -> head sha) pin it to them, so a row
written before a branch was rewritten is never mistaken for an answer about
the rewritten branch (i2mint/mergeset#23). Rows written before pinning
existed carry neither and read back as *unpinned*; see
[`mergeset.log.EvaluationLog`](mergeset.log.md#mergeset.log.EvaluationLog).

#### base_sha *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

Full sha of the base the set was merged onto. `None` on unpinned rows.

#### cached *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

True when this came from the log rather than from a real run. Not
serialized: it is a fact about *this* lookup, not about the evaluation.

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.base.Evaluation.to_jdict).

* **Return type:**
  [`Evaluation`](#mergeset.base.Evaluation)

#### heads *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

Full head sha of each change in `subset` when it was evaluated.

#### *property* ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the set evaluated as good.

#### *property* pinned *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the row records which commits it was evaluated against.

#### to_jdict()

JSON-able view; `subset` becomes a sorted list.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* mergeset.base.Evaluator(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Callable that decides whether a change set is good.

This is *the* expensive seam: one call is typically a merge plus a test run.

### mergeset.base.MergeFn

(changes to merge, in order) -> outcome + a tree to validate.

* **Type:**
  A merge function

alias of `Callable`[[…], [`MergeOutcome`](#mergeset.base.MergeOutcome)]

### *class* mergeset.base.MergeOutcome(ok, reason='conflict', conflicting_files=(), assisted=False, assist_diff=None, order=(), detail='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of merging a change set onto its base.

`reason` is load-bearing. “These changes conflict with each other” and “we
could not run the experiment” are completely different facts, and conflating
them is how a run reports *0 of 15 mergeable, complete* with total
confidence when the real problem was a bad worktree path. Only
`reason == 'conflict'` may ever enter the conflict set; an `'error'`
aborts, because a set that was never tested has told us nothing.

#### reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'conflict'*

`'conflict'` (a real textual conflict) or `'error'` (the merge could
not be attempted: bad path, missing ref, unusable worktree).

#### to_jdict()

JSON-able view.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *exception* mergeset.base.MergesetError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Base class for errors this package raises deliberately.

### *class* mergeset.base.Stage(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Where an evaluation ended.

### *class* mergeset.base.StageRun(name, duration=0.0, returncode=None, skipped=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one stage of a staged validation did, and what it cost.

A stage skipped because its fingerprint matched (an install whose lockfile
did not change) is recorded too, with `skipped=True` and no time: that
skip is often the largest term in what an evaluation costs, and a log that
cannot show it cannot confirm it (i2mint/mergeset#17).

```pycon
>>> StageRun.from_jdict(StageRun('setup', 33.0, 0).to_jdict())
StageRun(name='setup', duration=33.0, returncode=0, skipped=False)
```

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.base.StageRun.to_jdict).

* **Return type:**
  [`StageRun`](#mergeset.base.StageRun)

#### to_jdict()

JSON-able view.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### mergeset.base.ValidateFn

(path to a merged worktree) -> outcome.

* **Type:**
  A validation function

alias of `Callable`[[…], [`ValidationOutcome`](#mergeset.base.ValidationOutcome)]

### *class* mergeset.base.ValidationOutcome(ok, failing_tests=(), failing_files=(), duration=0.0, stdout_tail='', returncode=None, stages=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of validating a merged tree.

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.base.ValidationOutcome.to_jdict); rows without `stages` read as none.

Keys it does not know are ignored, so a log written by a later version
still loads here instead of failing on its first new field.

* **Return type:**
  [`ValidationOutcome`](#mergeset.base.ValidationOutcome)

#### *property* stage_seconds *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

`{stage name: seconds}` for the stages that ran (skips excluded).

The shape [`mergeset.cost.Seconds`](mergeset.cost.md#mergeset.cost.Seconds) accepts as a breakdown. Two
stages sharing a name are summed, never overwritten.

```pycon
>>> ValidationOutcome(True, stages=[StageRun('setup', skipped=True),
...                                 StageRun('test', 6.0, 0)]).stage_seconds
{'test': 6.0}
```

#### stages *: [Sequence](https://docs.python.org/3/library/typing.html#typing.Sequence)[[StageRun](#mergeset.base.StageRun)]* *= ()*

Per-stage breakdown, in run order, for a staged validator; empty for a
single-command one and on rows written before stages were recorded.

#### to_jdict()

JSON-able view.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* mergeset.base.Verdict(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Outcome of evaluating a change set.

### mergeset.base.change_set(ids)

Normalize any iterable of change ids into a `frozenset`.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> change_set(['b', 'a', 'b']) == frozenset({'a', 'b'})
True
```

### mergeset.base.set_key(ids)

A stable, hashable, JSON-friendly key for a change set.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)

```pycon
>>> set_key({'b', 'a'})
('a', 'b')
```
