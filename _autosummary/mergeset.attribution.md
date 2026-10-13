# mergeset.attribution

From a failure to the changes that probably caused it.

When a set fails, the expensive information has already been paid for: the
runner said *what* failed. Turning that into “which of these changes did it”
saves the conflict-shrinking step several oracle calls, and on real failures it
lands directly on the culprit.

Three signals, in increasing order of how much they prove:

1. **Paths in the failure block.** Every path a failure mentions, not only the
   failing test’s own file — a stack trace’s actionable frame is usually a
   *source* file, and when a suite fails to load there are no test ids at all.
2. **The changes that touched those paths.** File-level attribution, the obvious
   move, and by itself frequently wrong: a drift test added by one change fails
   because of what a *different* change did to the sources it derives from.
3. **Identifiers named in the failure.** When the output quotes symbols — an
   assertion diff, an undefined name, a missing export — matching those against
   each candidate’s diff finds the change that introduced them even when it
   shares no file with the failing test. This is the only signal that gets that
   drift case right.

Everything here is a *hint*. A wrong hint costs the search one wasted check and
then it falls back to unguided shrinking; it never decides a verdict.

### Functions

| [`failure_text`](#mergeset.attribution.failure_text)(outcome)                          | Everything a validation outcome said, as one blob to mine.                                                         |
|-------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| [`git_diff_reader`](#mergeset.attribution.git_diff_reader)(repo, base, heads)             | A `diff_of` for [`suspects()`](#mergeset.attribution.suspects), reading (and caching) real git diffs. |
| [`identifiers_in`](#mergeset.attribution.identifiers_in)(text)                           | Camel/Pascal-case identifiers named in the failure output.                                                         |
| [`paths_in`](#mergeset.attribution.paths_in)(text)                                 | Every source-looking path mentioned, vendor directories excluded.                                                  |
| [`suspects`](#mergeset.attribution.suspects)(outcome, \*, files_by_change, within) | Changes the failure points at, or an empty set when it points nowhere.                                             |

### mergeset.attribution.failure_text(outcome)

Everything a validation outcome said, as one blob to mine.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.attribution.git_diff_reader(repo, base, heads)

A `diff_of` for [`suspects()`](#mergeset.attribution.suspects), reading (and caching) real git diffs.

### mergeset.attribution.identifiers_in(text)

Camel/Pascal-case identifiers named in the failure output.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> identifiers_in('+ "pointColorSeeds": { "$ref": "AxisDirectionType" }')
['pointColorSeeds', 'AxisDirectionType']
```

### mergeset.attribution.paths_in(text)

Every source-looking path mentioned, vendor directories excluded.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> paths_in('FAIL tests/unit/a.test.ts [ tests/unit/a.test.ts ]')
['tests/unit/a.test.ts']
>>> paths_in(' at Module.x node_modules/zod/util.js:15 then src/schemas.ts:89:4')
['src/schemas.ts']
```

### mergeset.attribution.suspects(outcome, , files_by_change, within, diff_of=None)

Changes the failure points at, or an empty set when it points nowhere.

* **Parameters:**
  * **outcome** ([`ValidationOutcome`](mergeset.base.md#mergeset.base.ValidationOutcome)) – The failed validation, with whatever the runner printed.
  * **files_by_change** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Which files each change touched.
  * **within** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Only these changes are candidates (the set being evaluated).
  * **diff_of** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `change id -> its diff text`. Optional but valuable: it is
    what enables identifier matching, the only signal that attributes a
    failure to a change sharing no file with the failing test.
* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)
* **Returns:**
  A strict, non-empty subset of `within`, or `frozenset()` when the
  evidence is absent, useless, or implicates everything (in which case it
  has told us nothing and blind shrinking is the honest fallback).

```pycon
>>> out = ValidationOutcome(ok=False, failing_tests=['tests/a.test.ts::x'])
>>> set(suspects(out, files_by_change={'p1': ['tests/a.test.ts'], 'p2': ['b.ts']},
...              within=['p1', 'p2']))
{'p1'}
```
