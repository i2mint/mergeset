# mergeset.validation

Validation functions: does this merged tree actually work?

A validator is any callable `(worktree_path) -> ValidationOutcome`. Four are
shipped — a pytest runner (the default), an arbitrary shell command, a local CI
run via `act`, and “merge-only” — and a user-supplied Python callable is a
first-class fifth option, because the interesting projects always have one more
step than a test command.

Every validator returns a *structured* result, not a bit: which tests failed,
which files they live in, how long it took. The solver uses that to aim its
conflict shrinking at the changes actually implicated, rather than halving
blindly.

### Module Attributes

| [`DEFAULT_PYTEST_ARGS`](#mergeset.validation.DEFAULT_PYTEST_ARGS)   | the answer we need is a bit, and the first failure has it.   |
|------------------------------------------------------------------------|--------------------------------------------------------------|

### Functions

| [`act_validation`](#mergeset.validation.act_validation)(\*[, job, timeout, env])          | A validator that runs the repository's GitHub Actions locally with `act`.                                                  |
|---------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| [`callable_validation`](#mergeset.validation.callable_validation)(func)                        | Adapt a plain user callable into a validator.                                                                              |
| [`check_validation_capability`](#mergeset.validation.check_validation_capability)(path[, runner])      | Raise a *fixable* error if `runner` cannot work on `path`.                                                                 |
| [`command_validation`](#mergeset.validation.command_validation)(command, \*[, timeout, env])  | A validator that runs an arbitrary shell command in the merged worktree.                                                   |
| [`detect_runner`](#mergeset.validation.detect_runner)(path)                              | Guess how this project is tested; `None` if nothing is recognizable.                                                       |
| [`file_fingerprint`](#mergeset.validation.file_fingerprint)(\*paths)                        | A fingerprint function over the contents of the given repo-relative files.                                                 |
| [`flake_tolerant`](#mergeset.validation.flake_tolerant)(validate, \*[, retries])          | Re-run a failing validation `retries` times before believing it.                                                           |
| [`js_validation`](#mergeset.validation.js_validation)(\*[, install, build, test, ...])   | A staged validator shaped like a JavaScript project.                                                                       |
| [`merge_only_validation`](#mergeset.validation.merge_only_validation)()                          | A validator that accepts anything that merged cleanly.                                                                     |
| [`pytest_validation`](#mergeset.validation.pytest_validation)(\*[, args, timeout, env, ...]) | A validator that runs the project's pytest suite, fail-fast by default.                                                    |
| [`staged_validation`](#mergeset.validation.staged_validation)(stages, \*[, env])             | Run an ordered list of [`ValidationStage`](#mergeset.validation.ValidationStage) steps, reporting which one failed. |

### Classes

| [`ValidationStage`](#mergeset.validation.ValidationStage)(name, command[, ...])   | One step of a staged validation.   |
|------------------------------------------------------------------------------------------|------------------------------------|

### mergeset.validation.DEFAULT_PYTEST_ARGS *= ('-x', '-q', '--tb=short', '-p', 'no:cacheprovider')*

the answer we need is a bit, and the first failure has it.

* **Type:**
  Fail-fast by default

### *class* mergeset.validation.ValidationStage(name, command, fingerprint=None, timeout=None, required=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One step of a staged validation.

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What this step is (`setup`, `build`, `test`, `lint`…).
    It ends up in the log and in the report, which is the whole point:
    “failed to build” and “tests failed” are different facts and a
    single pass/fail bit throws away the one you need.
  * **command** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Shell command, run in the merged worktree.
  * **fingerprint** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Optional `worktree -> str`. When given, the stage is
    skipped if it already ran in this worktree with the same value —
    this is how an expensive dependency install is amortized across
    evaluations instead of being paid every time (keyed on, say, the
    hash of the lockfile).
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the stage is declared failed.
  * **required** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – A failing required stage fails the whole validation and stops
    the sequence (the default). A non-required stage’s failure is
    recorded in `failing_tests` and the set still counts as good —
    for an advisory pass, such as a lint the project runs as a separate
    CI job rather than a gate.

### mergeset.validation.act_validation(, job=None, timeout=None, env=None)

A validator that runs the repository’s GitHub Actions locally with `act`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.callable_validation(func)

Adapt a plain user callable into a validator.

The callable may return a `ValidationOutcome` (used as-is) or
anything truthy/falsy (interpreted as pass/fail).

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.check_validation_capability(path, runner='pytest')

Raise a *fixable* error if `runner` cannot work on `path`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### mergeset.validation.command_validation(command, , timeout=None, env=None)

A validator that runs an arbitrary shell command in the merged worktree.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.detect_runner(path)

Guess how this project is tested; `None` if nothing is recognizable.

Ordering matters more than it looks. An earlier version checked for a
`tests/` directory in the same breath as `pyproject.toml`, and so
classified a TypeScript repository as pytest and ran pytest in it for a
dozen evaluations before anyone noticed. Manifests decide; a `tests/`
directory is not evidence of a language.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> detect_runner('/definitely/not/a/project') is None
True
```

### mergeset.validation.file_fingerprint(\*paths)

A fingerprint function over the contents of the given repo-relative files.

The canonical use is a lockfile: install dependencies again only when
`pnpm-lock.yaml` actually changed between two candidate merges.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.validation.flake_tolerant(validate, , retries=1)

Re-run a failing validation `retries` times before believing it.

Monotonicity is a prior, not a law, and flaky tests are the usual way it
breaks. This is the cheap defense; the honest one is
`EvaluationLog.monotonicity_violations`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.js_validation(, install='pnpm install --frozen-lockfile', build=None, test='pnpm run test', lint=None, lockfile='pnpm-lock.yaml', timeout=None)

A staged validator shaped like a JavaScript project.

Install is fingerprinted on the lockfile so it runs only when dependencies
actually changed; the build, when given, is a required prerequisite of the
tests rather than part of them.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.merge_only_validation()

A validator that accepts anything that merged cleanly.

Useful as a first pass: it costs nothing and still finds every textual
conflict, which on real branch sets is most of them.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.pytest_validation(, args=('-x', '-q', '--tb=short', '-p', 'no:cacheprovider'), timeout=None, env=None, select_paths=None)

A validator that runs the project’s pytest suite, fail-fast by default.

* **Parameters:**
  * **args** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Passed to pytest. Fail-fast (`-x`) is the default because the
    oracle only needs to know *whether* the set is good.
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is declared failed.
  * **env** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Extra environment variables.
  * **select_paths** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `worktree -> test paths` — the seam for test-impact
    selection. Return only the tests the merged changes can affect and
    each evaluation gets dramatically cheaper. Default: run everything.
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.staged_validation(stages, , env=None)

Run an ordered list of [`ValidationStage`](#mergeset.validation.ValidationStage) steps, reporting which one failed.

Real projects do not have “the test command”; they have a sequence, and the
steps are not equally interesting. A JS repo may need
`pnpm install` (slow, only when the lockfile moved), then a build (a
*prerequisite* of testing — without it the tests do not even collect, and a
validator that skipped it would report a false failure), then the tests,
then a lint pass.

The failing stage’s name is prefixed onto every reported failure id, so the
log distinguishes `build: ...` from `test: tests/x.ts::y`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]
