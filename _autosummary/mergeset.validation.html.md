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

A validator may also say *what* it runs: a `validator_fingerprint` attribute,
a short digest of its command, stages, timeout and environment. Every shipped
validator carries one, and the evaluation log stamps it on each row, so a row
recorded by `pytest -x` never answers a question asked of `pytest -m e2e`
(i2mint/mergeset#32). A user callable has none unless it sets one, since only its
author knows what changes its verdicts:
`my_validator.validator_fingerprint = 'smoke-v2'`. Its rows are stamped
`UNKNOWN_FINGERPRINT`, which matches only other such rows. A wrapper made
with `functools.wraps` copies the wrapped validator’s fingerprint along with
its `__dict__`; a wrapper that changes what is checked must set its own.

A fingerprint covers the command’s *text*. When the command runs a script that
lives outside the analysed repository (`python ~/checks/smoke.py`), the
script’s contents are not in it: files inside the repository are pinned by the
commits, files outside it are not. Name such files with `inputs=` and their
contents join the fingerprint, so editing the script retires the verdicts it
gave (i2mint/mergeset#39).

### Module Attributes

| [`DEFAULT_PYTEST_ARGS`](#mergeset.validation.DEFAULT_PYTEST_ARGS)   | the answer we need is a bit, and the first failure has it.                                                                                                            |
|------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`FINGERPRINT_ATTR`](#mergeset.validation.FINGERPRINT_ATTR)      | The attribute a validator carries to say what it runs (i2mint/mergeset#32).                                                                                           |
| [`RACY_SECONDS`](#mergeset.validation.RACY_SECONDS)          | How old a file's last change must be before its stat may vouch for its contents.                                                                                      |
| [`MAX_CACHED_DIGESTS`](#mergeset.validation.MAX_CACHED_DIGESTS)    | How many file digests [`FILE_DIGESTS`](#mergeset.validation.FILE_DIGESTS) holds before it starts over: about 110 MiB, room for a large virtual environment. |
| [`FILE_DIGESTS`](#mergeset.validation.FILE_DIGESTS)          | Content digests of input files, keyed by the file's path and stat (#42).                                                                                              |

### Functions

| [`act_validation`](#mergeset.validation.act_validation)(\*[, job, timeout, env, inputs])   | A validator that runs the repository's GitHub Actions locally with `act`.                                                  |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| [`callable_validation`](#mergeset.validation.callable_validation)(func)                         | Adapt a plain user callable into a validator.                                                                              |
| [`check_validation_capability`](#mergeset.validation.check_validation_capability)(path[, runner])       | Raise a *fixable* error if `runner` cannot work on `path`.                                                                 |
| [`command_validation`](#mergeset.validation.command_validation)(command, \*[, timeout, ...])   | A validator that runs an arbitrary shell command in the merged worktree.                                                   |
| [`detect_runner`](#mergeset.validation.detect_runner)(path)                               | Guess how this project is tested; `None` if nothing is recognizable.                                                       |
| [`file_fingerprint`](#mergeset.validation.file_fingerprint)(\*paths)                         | A fingerprint function over the contents of the given repo-relative files.                                                 |
| [`fingerprint_of`](#mergeset.validation.fingerprint_of)(validate)                          | What `validate` runs, as a short string -- or `None` when it cannot say.                                                   |
| [`flake_tolerant`](#mergeset.validation.flake_tolerant)(validate, \*[, retries])           | Re-run a failing validation `retries` times before believing it.                                                           |
| [`inputs_digest`](#mergeset.validation.inputs_digest)(paths, \*[, cache])                 | A digest of each path's current contents, keyed by its real path.                                                          |
| [`js_validation`](#mergeset.validation.js_validation)(\*[, install, build, test, ...])    | A staged validator shaped like a JavaScript project.                                                                       |
| [`merge_only_validation`](#mergeset.validation.merge_only_validation)()                           | A validator that accepts anything that merged cleanly.                                                                     |
| [`pytest_validation`](#mergeset.validation.pytest_validation)(\*[, args, timeout, env, ...])  | A validator that runs the project's pytest suite, fail-fast by default.                                                    |
| [`recorded_fingerprint`](#mergeset.validation.recorded_fingerprint)(validate)                    | The fingerprint a log row records for `validate`: never `None`.                                                            |
| [`staged_validation`](#mergeset.validation.staged_validation)(stages, \*[, env, inputs])      | Run an ordered list of [`ValidationStage`](#mergeset.validation.ValidationStage) steps, reporting which one failed. |

### Classes

| [`ValidationStage`](#mergeset.validation.ValidationStage)(name, command[, ...])   | One step of a staged validation.   |
|------------------------------------------------------------------------------------------|------------------------------------|

### mergeset.validation.DEFAULT_PYTEST_ARGS *= ('-x', '-q', '--tb=short', '-p', 'no:cacheprovider')*

the answer we need is a bit, and the first failure has it.

* **Type:**
  Fail-fast by default

### mergeset.validation.FILE_DIGESTS *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {}*

Content digests of input files, keyed by the file’s path and stat (#42).
Reading an 8.5 GB tree takes about a minute; stat-ing it, seconds. A run
digests its inputs once per validator built and twice around every
evaluation, so all but the first read come from here.

### mergeset.validation.FINGERPRINT_ATTR *= 'validator_fingerprint'*

The attribute a validator carries to say what it runs (i2mint/mergeset#32).

### mergeset.validation.MAX_CACHED_DIGESTS *= 250000*

How many file digests [`FILE_DIGESTS`](#mergeset.validation.FILE_DIGESTS) holds before it starts over:
about 110 MiB, room for a large virtual environment.

### mergeset.validation.RACY_SECONDS *= 2.0*

How old a file’s last change must be before its stat may vouch for its
contents. An edit within one timestamp tick of a read leaves size and mtime
as they were (git’s “racy clean” problem); 2 s covers the coarsest common
filesystem timestamps (FAT). Younger files are always read.

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

### mergeset.validation.act_validation(, job=None, timeout=None, env=None, inputs=())

A validator that runs the repository’s GitHub Actions locally with `act`.

`inputs`: files outside the repository that change verdicts (an
`.actrc`, a secrets file); see [`inputs_digest()`](#mergeset.validation.inputs_digest).

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

### mergeset.validation.command_validation(command, , timeout=None, env=None, inputs=())

A validator that runs an arbitrary shell command in the merged worktree.

`inputs` names the files outside the repository the command runs, such as
the script in `python ~/checks/smoke.py`: their contents join the
validator’s fingerprint, so an edited script is not answered by the old
script’s verdicts (see [`inputs_digest()`](#mergeset.validation.inputs_digest)).

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

### mergeset.validation.fingerprint_of(validate)

What `validate` runs, as a short string – or `None` when it cannot say.

Two validators with the same fingerprint give the same verdict on the same
tree, so an evaluation log may answer one with the other’s rows. `None`
means unknown: such a validator’s rows are recorded as
`UNKNOWN_FINGERPRINT` (see [`recorded_fingerprint()`](#mergeset.validation.recorded_fingerprint)), and answer
only other validators that cannot say what they run either.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> fingerprint_of(command_validation('make test')) == fingerprint_of(
...     command_validation('make test'))
True
>>> fingerprint_of(command_validation('make test')) == fingerprint_of(
...     command_validation('make check'))
False
>>> fingerprint_of(command_validation('make test')).startswith('command:')
True
>>> fingerprint_of(lambda worktree: True) is None
True
```

### mergeset.validation.flake_tolerant(validate, , retries=1)

Re-run a failing validation `retries` times before believing it.

Monotonicity is a prior, not a law, and flaky tests are the usual way it
breaks. This is the cheap defense; the honest one is
`EvaluationLog.monotonicity_violations`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.inputs_digest(paths, , cache=FILE_DIGESTS)

A digest of each path’s current contents, keyed by its real path.

These are the files a validator runs that its command text does not
capture: a script outside the analysed repository, a config it reads. A
directory is digested over every file under it (names and contents,
following symlinks, each directory once; `__pycache__`, `*.pyc` and
dot-directories such as `.git` are left out, since running the inputs
writes them), a missing path as `'missing'`
– so creating it later changes the digest too – and one that cannot be
read as `'unreadable'`. Relative paths are resolved against the current
directory, *not* the worktree: files inside the repository are already
pinned by the commits. `paths` is a collection of paths: a lone string is
refused, since it would be read one character at a time.

A file whose path, inode, size, mtime and ctime match an earlier read is
not read again: its digest comes from `cache` (default
[`FILE_DIGESTS`](#mergeset.validation.FILE_DIGESTS)), but only once its last change (mtime or ctime,
which no tool can set back) is [`RACY_SECONDS`](#mergeset.validation.RACY_SECONDS) older than that read.
`cache=None` reads every file.

Trusting a stat is what `make` and `git` do, with their blind spots: a
second write through a shared `mmap` to an already-dirty page changes
no timestamp, and a network filesystem may serve cached attributes (NFS,
for up to a minute) or stamp times from a clock behind this one. For inputs
edited that way, pass `cache=None`, or set
`mergeset.validation.FILE_DIGESTS = None` to turn the cache off for every
validator (ADR 0035).

* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> import tempfile
>>> with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
...     _ = f.write('print(1)')
>>> before = inputs_digest([f.name])
>>> with open(f.name, 'w') as g:
...     _ = g.write('print(2)')
>>> inputs_digest([f.name]) == before
False
>>> os.remove(f.name)
>>> list(inputs_digest([f.name]).values())
['missing']
```

### mergeset.validation.js_validation(, install='pnpm install --frozen-lockfile', build=None, test='pnpm run test', lint=None, lockfile='pnpm-lock.yaml', timeout=None, inputs=())

A staged validator shaped like a JavaScript project.

Install is fingerprinted on the lockfile so it runs only when dependencies
actually changed; the build, when given, is a required prerequisite of the
tests rather than part of them. `inputs`: files outside the repository
that any step runs (see [`inputs_digest()`](#mergeset.validation.inputs_digest)).

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.merge_only_validation()

A validator that accepts anything that merged cleanly.

Useful as a first pass: it costs nothing and still finds every textual
conflict, which on real branch sets is most of them.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.pytest_validation(, args=('-x', '-q', '--tb=short', '-p', 'no:cacheprovider'), timeout=None, env=None, select_paths=None, inputs=())

A validator that runs the project’s pytest suite, fail-fast by default.

* **Parameters:**
  * **args** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Passed to pytest. Fail-fast (`-x`) is the default because the
    oracle only needs to know *whether* the set is good.
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is declared failed.
  * **env** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Extra environment variables.
  * **select_paths** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `worktree -> test paths` — the seam for test-impact
    selection. Return only the tests the merged changes can affect and
    each evaluation gets dramatically cheaper. Default: run everything.
  * **inputs** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Files outside the repository whose contents change verdicts
    (a shared `conftest.py`, a plugin); see [`inputs_digest()`](#mergeset.validation.inputs_digest).
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.validation.recorded_fingerprint(validate)

The fingerprint a log row records for `validate`: never `None`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> recorded_fingerprint(lambda worktree: True)
'unknown'
```

### mergeset.validation.staged_validation(stages, , env=None, inputs=())

Run an ordered list of [`ValidationStage`](#mergeset.validation.ValidationStage) steps, reporting which one failed.

Real projects do not have “the test command”; they have a sequence, and the
steps are not equally interesting. A JS repo may need
`pnpm install` (slow, only when the lockfile moved), then a build (a
*prerequisite* of testing — without it the tests do not even collect, and a
validator that skipped it would report a false failure), then the tests,
then a lint pass.

The failing stage’s name is prefixed onto every reported failure id, so the
log distinguishes `build: ...` from `test: tests/x.ts::y`.

`inputs` names files outside the repository that any stage runs; their
contents join the fingerprint (see [`inputs_digest()`](#mergeset.validation.inputs_digest)).

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]
