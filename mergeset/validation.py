"""Validation functions: does this merged tree actually work?

A validator is any callable ``(worktree_path) -> ValidationOutcome``. Four are
shipped — a pytest runner (the default), an arbitrary shell command, a local CI
run via ``act``, and "merge-only" — and a user-supplied Python callable is a
first-class fifth option, because the interesting projects always have one more
step than a test command.

Every validator returns a *structured* result, not a bit: which tests failed,
which files they live in, how long it took. The solver uses that to aim its
conflict shrinking at the changes actually implicated, rather than halving
blindly.

A validator may also say *what* it runs: a ``validator_fingerprint`` attribute,
a short digest of its command, stages, timeout and environment. Every shipped
validator carries one, and the evaluation log stamps it on each row, so a row
recorded by ``pytest -x`` never answers a question asked of ``pytest -m e2e``
(i2mint/mergeset#32). A user callable has none unless it sets one, since only its
author knows what changes its verdicts:
``my_validator.validator_fingerprint = 'smoke-v2'``. Its rows are stamped
:data:`UNKNOWN_FINGERPRINT`, which matches only other such rows. A wrapper made
with ``functools.wraps`` copies the wrapped validator's fingerprint along with
its ``__dict__``; a wrapper that changes what is checked must set its own.

A fingerprint covers the command's *text*. When the command runs a script that
lives outside the analysed repository (``python ~/checks/smoke.py``), the
script's contents are not in it: files inside the repository are pinned by the
commits, files outside it are not. Name such files with ``inputs=`` and their
contents join the fingerprint, so editing the script retires the verdicts it
gave (i2mint/mergeset#39).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from mergeset.base import (
    UNKNOWN_FINGERPRINT,
    CapabilityError,
    StageRun,
    ValidationOutcome,
)

#: Fail-fast by default: the answer we need is a bit, and the first failure has it.
DEFAULT_PYTEST_ARGS = ("-x", "-q", "--tb=short", "-p", "no:cacheprovider")

_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


#: Files that *identify* an ecosystem, in decreasing order of how much they
#: prove. A bare ``tests/`` directory proves nothing -- every language has one --
#: so it must never outrank a manifest.
_RUNNER_EVIDENCE = (
    ("pytest", ("pytest.ini", "tox.ini")),
    ("pytest", ("pyproject.toml", "setup.cfg", "setup.py")),
    ("npm", ("package.json",)),
    ("make", ("Makefile",)),
)


#: The attribute a validator carries to say what it runs (i2mint/mergeset#32).
FINGERPRINT_ATTR = "validator_fingerprint"


def fingerprint_of(validate: Optional[Callable]) -> Optional[str]:
    """What ``validate`` runs, as a short string -- or ``None`` when it cannot say.

    Two validators with the same fingerprint give the same verdict on the same
    tree, so an evaluation log may answer one with the other's rows. ``None``
    means unknown: such a validator's rows are recorded as
    :data:`UNKNOWN_FINGERPRINT` (see :func:`recorded_fingerprint`), and answer
    only other validators that cannot say what they run either.

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
    """
    value = getattr(validate, FINGERPRINT_ATTR, None)
    # A blank fingerprint says nothing either, and must not become a real one
    # when wrapped (``flake_tolerant`` digests what it wraps).
    return str(value) if value not in (None, "") else None


def recorded_fingerprint(validate: Optional[Callable]) -> str:
    """The fingerprint a log row records for ``validate``: never ``None``.

    >>> recorded_fingerprint(lambda worktree: True)
    'unknown'
    """
    return fingerprint_of(validate) or UNKNOWN_FINGERPRINT


#: How old a file's last change must be before its stat may vouch for its
#: contents. An edit within one timestamp tick of a read leaves size and mtime
#: as they were (git's "racy clean" problem); 2 s covers the coarsest common
#: filesystem timestamps (FAT). Younger files are always read.
RACY_SECONDS = 2.0

#: How many file digests :data:`FILE_DIGESTS` holds before it starts over.
MAX_CACHED_DIGESTS = 1_000_000

#: Content digests of input files, keyed by the file's path and stat (#42).
#: Reading an 8.5 GB tree takes about a minute; stat-ing it, seconds. A run
#: digests its inputs once per validator built and twice around every
#: evaluation, so all but the first read come from here.
FILE_DIGESTS: Dict[tuple, str] = {}


def inputs_digest(
    paths: Iterable[str], *, cache: Optional[Dict[tuple, str]] = FILE_DIGESTS
) -> Dict[str, str]:
    """A digest of each path's current contents, keyed by its real path.

    These are the files a validator runs that its command text does not
    capture: a script outside the analysed repository, a config it reads. A
    directory is digested over every file under it (names and contents,
    following symlinks, each directory once; ``__pycache__``, ``*.pyc`` and
    dot-directories such as ``.git`` are left out, since running the inputs
    writes them), a missing path as ``'missing'``
    -- so creating it later changes the digest too -- and one that cannot be
    read as ``'unreadable'``. Relative paths are resolved against the current
    directory, *not* the worktree: files inside the repository are already
    pinned by the commits. ``paths`` is a collection of paths: a lone string is
    refused, since it would be read one character at a time.

    A file whose path, inode, size, mtime and ctime match an earlier read is
    not read again: its digest comes from ``cache`` (default
    :data:`FILE_DIGESTS`), but only once its last change (mtime or ctime,
    which no tool can set back) is :data:`RACY_SECONDS` older than that read.
    ``cache=None`` reads every file.

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
    """

    if isinstance(paths, (str, bytes, os.PathLike)):
        raise TypeError(
            f"inputs is a collection of paths, got the single path {paths!r}: "
            f"wrap it in a list, inputs=[{paths!r}]."
        )

    def file_digest(path: str) -> str:
        stat = os.stat(path)
        key = (
            path,
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
        if cache is not None and key in cache:
            return cache[key]
        reading_from = time.time_ns()
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        value = digest.hexdigest()[:16]
        changed = max(stat.st_mtime_ns, stat.st_ctime_ns)
        if cache is not None and changed < reading_from - RACY_SECONDS * 1e9:
            # Any later edit stamps a time after `reading_from`, so the key it
            # leaves behind cannot be this one.
            if len(cache) >= MAX_CACHED_DIGESTS:
                cache.clear()
            cache[key] = value
        return value

    def tree_digest(path: str) -> str:
        digest = hashlib.sha256()
        seen = set()

        def unreadable(error: OSError) -> None:
            digest.update(f"unreadable:{error.filename}".encode() + b"\0")

        for root, dirs, files in os.walk(path, followlinks=True, onerror=unreadable):
            real = os.path.realpath(root)
            if real in seen:  # a symlink loop, or the same directory twice
                dirs[:] = []
                continue
            seen.add(real)
            # What running the inputs writes beside them (a bytecode cache, a
            # tool's cache directory) is not what they are: counting it would
            # stop the first run of a script that imports a sibling.
            dirs[:] = sorted(
                d for d in dirs if d != "__pycache__" and not d.startswith(".")
            )
            files = [f for f in files if not f.endswith((".pyc", ".pyo"))]
            for name in sorted(files):
                full = os.path.join(root, name)
                digest.update(os.path.relpath(full, path).encode() + b"\0")
                digest.update(digest_of(full).encode())
        return digest.hexdigest()[:16]

    def digest_of(path: str) -> str:
        try:
            if os.path.isfile(path):
                return file_digest(path)
            if os.path.isdir(path):
                return tree_digest(path)
        except OSError:
            return "unreadable"
        return "missing"

    real = (os.path.realpath(os.path.expanduser(os.fspath(p))) for p in paths)
    return {path: digest_of(path) for path in sorted(set(real))}


def _same_verdicts(**spec: Any) -> Dict[str, Any]:
    """``spec`` with the spellings that run identically made identical.

    ``env=None`` and ``env={}`` run the same command, and so do ``timeout=60``
    and ``timeout=60.0``; a fingerprint that told them apart would only cost a
    re-run.
    """
    if "env" in spec:
        spec["env"] = spec["env"] or None
    if spec.get("timeout") is not None:
        spec["timeout"] = float(spec["timeout"])
    if "inputs" in spec:
        # No inputs digests like before they existed, so naming none never
        # retires a log's rows.
        inputs = spec.pop("inputs")
        if isinstance(inputs, (str, bytes, os.PathLike)) or inputs:
            spec["inputs"] = inputs_digest(inputs)
    return spec


def _fingerprinted(validate: Callable, kind: str, **spec: Any) -> Callable:
    """Attach the fingerprint of ``kind`` and ``spec`` to ``validate``; return it.

    The digest is over everything that can change a verdict: the command, the
    timeout (a timeout is a FAIL), the environment, the retries, and the
    contents of the ``inputs`` the command runs (see :func:`inputs_digest`),
    read now, when the validator is made. ``kind`` stays
    readable in front of it, for a person looking at a log row.
    """
    inputs = spec.get("inputs") or ()
    if not isinstance(inputs, (str, bytes, os.PathLike)):
        # Read once: a generator digested here would be empty when the
        # validator checks its inputs again around each run.
        inputs = spec["inputs"] = list(inputs)
    spec = _same_verdicts(**spec)
    payload = json.dumps({"kind": kind, **spec}, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    if "inputs" in spec:
        validate = _inputs_held(validate, inputs, spec["inputs"])
    setattr(validate, FINGERPRINT_ATTR, f"{kind}:{digest}")
    return validate


def _inputs_held(
    validate: Callable, inputs: Sequence[str], digested: Dict[str, str]
) -> Callable:
    """``validate``, refusing to run once ``inputs`` differ from ``digested``.

    The fingerprint is made once, from the inputs as they were; the command
    reads them afresh on every run. An input edited mid-run would be judged
    by the new script and recorded under the old one's fingerprint, so that
    reverting the edit later would let those rows answer the old script. A
    verdict reached either side of the edit is refused instead, and the run
    stops with the reason: the next run digests the new contents. The inputs
    are digested twice per run, before and after; keep them to the files the
    command reads, not a whole environment.
    """

    def check(when: str) -> None:
        if inputs_digest(inputs) != digested:
            changed = sorted(
                p for p, d in inputs_digest(inputs).items() if digested.get(p) != d
            )
            raise CapabilityError(
                f"A validation input changed {when} ({', '.join(changed)}). "
                "Verdicts are recorded under the inputs as they were when the "
                "validator was made, so this run cannot record any more of them. "
                "Run again: the new contents get their own fingerprint."
            )

    @functools.wraps(validate)
    def validate_with_inputs(worktree: str) -> ValidationOutcome:
        check("since the validator was made")
        outcome = validate(worktree)
        check("while it ran")
        return outcome

    return validate_with_inputs


def detect_runner(path: str) -> Optional[str]:
    """Guess how this project is tested; ``None`` if nothing is recognizable.

    Ordering matters more than it looks. An earlier version checked for a
    ``tests/`` directory in the same breath as ``pyproject.toml``, and so
    classified a TypeScript repository as pytest and ran pytest in it for a
    dozen evaluations before anyone noticed. Manifests decide; a ``tests/``
    directory is not evidence of a language.

    >>> detect_runner('/definitely/not/a/project') is None
    True
    """
    if not os.path.isdir(path):
        return None
    names = set(os.listdir(path))
    for runner, markers in _RUNNER_EVIDENCE:
        if names & set(markers):
            return runner
    return None


def check_validation_capability(path: str, runner: str = "pytest") -> None:
    """Raise a *fixable* error if ``runner`` cannot work on ``path``."""
    if runner == "pytest":
        if shutil.which("pytest") is None:
            raise CapabilityError(
                "pytest is not on PATH. `pip install pytest` in the environment "
                "mergeset runs in, or pass a different validator "
                "(e.g. `--validate-command 'make test'`)."
            )
        detected = detect_runner(path)
        if detected != "pytest":
            found = (
                f"it looks like a {detected} project"
                if detected
                else "no project manifest was found there"
            )
            raise CapabilityError(
                f"The default validator runs pytest, but {found} ({path}). "
                "Running the wrong test command produces confident nonsense, so "
                "mergeset refuses to guess. Pass the project's real command "
                "(--validate-command 'pnpm run test', or staged_validation([...]) "
                "from the library), or --merge-only to check mergeability alone."
            )
    elif runner == "act":
        if shutil.which("act") is None:
            raise CapabilityError(
                "`act` is not installed; it is what runs GitHub Actions locally. "
                "Install it (https://github.com/nektos/act) or use "
                "--validate-command / the default pytest validator."
            )


def _failing_test_ids(output: str) -> list:
    """Test ids pytest reported as failed or errored.

    >>> _failing_test_ids('FAILED tests/test_a.py::test_x - AssertionError\\n')
    ['tests/test_a.py::test_x']
    """
    return list(dict.fromkeys(_FAILED_LINE.findall(output)))


def _files_of(test_ids: Iterable[str]) -> list:
    """The files the failing tests live in.

    >>> _files_of(['tests/test_a.py::test_x', 'tests/test_a.py::test_y'])
    ['tests/test_a.py']
    """
    return list(dict.fromkeys(t.split("::", 1)[0] for t in test_ids))


def _run(
    cmd: Sequence[str],
    cwd: str,
    *,
    timeout: Optional[float],
    env: Optional[dict],
    shell: bool = False,
    tail_chars: int = 4000,
) -> ValidationOutcome:
    started = time.time()
    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run(
            cmd if not shell else " ".join(cmd),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
            shell=shell,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        returncode = proc.returncode
    except subprocess.TimeoutExpired as e:
        output = (e.stdout or "") if isinstance(e.stdout, str) else ""
        returncode = -1
        output += f"\n[mergeset] timed out after {timeout}s"
    failing = _failing_test_ids(output)
    return ValidationOutcome(
        ok=returncode == 0,
        failing_tests=failing,
        failing_files=_files_of(failing),
        duration=time.time() - started,
        stdout_tail=output[-tail_chars:],
        returncode=returncode,
    )


def pytest_validation(
    *,
    args: Sequence[str] = DEFAULT_PYTEST_ARGS,
    timeout: Optional[float] = None,
    env: Optional[dict] = None,
    select_paths: Optional[Callable[[str], Sequence[str]]] = None,
    inputs: Sequence[str] = (),
) -> Callable[[str], ValidationOutcome]:
    """A validator that runs the project's pytest suite, fail-fast by default.

    Args:
        args: Passed to pytest. Fail-fast (``-x``) is the default because the
            oracle only needs to know *whether* the set is good.
        timeout: Seconds before the run is declared failed.
        env: Extra environment variables.
        select_paths: ``worktree -> test paths`` — the seam for test-impact
            selection. Return only the tests the merged changes can affect and
            each evaluation gets dramatically cheaper. Default: run everything.
        inputs: Files outside the repository whose contents change verdicts
            (a shared ``conftest.py``, a plugin); see :func:`inputs_digest`.
    """

    def validate(worktree: str) -> ValidationOutcome:
        paths = list(select_paths(worktree)) if select_paths else []
        return _run(["pytest", *args, *paths], worktree, timeout=timeout, env=env)

    if select_paths is not None:
        # Which tests run is now decided by a callable, and a callable's name
        # says nothing about what it selects: leave the fingerprint unknown.
        if inputs:
            raise ValueError(
                "pytest_validation(select_paths=...) has no fingerprint (only "
                "its author knows what the callable selects), so inputs= would "
                "be ignored. Drop inputs, or set validator_fingerprint on the "
                "returned validator yourself."
            )
        return validate
    return _fingerprinted(
        validate, "pytest", args=list(args), timeout=timeout, env=env, inputs=inputs
    )


def command_validation(
    command: str,
    *,
    timeout: Optional[float] = None,
    env: Optional[dict] = None,
    inputs: Sequence[str] = (),
) -> Callable[[str], ValidationOutcome]:
    """A validator that runs an arbitrary shell command in the merged worktree.

    ``inputs`` names the files outside the repository the command runs, such as
    the script in ``python ~/checks/smoke.py``: their contents join the
    validator's fingerprint, so an edited script is not answered by the old
    script's verdicts (see :func:`inputs_digest`).
    """

    def validate(worktree: str) -> ValidationOutcome:
        return _run([command], worktree, timeout=timeout, env=env, shell=True)

    return _fingerprinted(
        validate, "command", command=command, timeout=timeout, env=env, inputs=inputs
    )


def act_validation(
    *,
    job: Optional[str] = None,
    timeout: Optional[float] = None,
    env: Optional[dict] = None,
    inputs: Sequence[str] = (),
) -> Callable[[str], ValidationOutcome]:
    """A validator that runs the repository's GitHub Actions locally with ``act``.

    ``inputs``: files outside the repository that change verdicts (an
    ``.actrc``, a secrets file); see :func:`inputs_digest`.
    """

    def validate(worktree: str) -> ValidationOutcome:
        check_validation_capability(worktree, "act")
        cmd = ["act", "-q"] + (["-j", job] if job else [])
        return _run(cmd, worktree, timeout=timeout, env=env)

    return _fingerprinted(
        validate, "act", job=job, timeout=timeout, env=env, inputs=inputs
    )


def callable_validation(
    func: Callable[[str], object],
) -> Callable[[str], ValidationOutcome]:
    """Adapt a plain user callable into a validator.

    The callable may return a :class:`ValidationOutcome` (used as-is) or
    anything truthy/falsy (interpreted as pass/fail).
    """

    def validate(worktree: str) -> ValidationOutcome:
        started = time.time()
        result = func(worktree)
        if isinstance(result, ValidationOutcome):
            return result
        return ValidationOutcome(ok=bool(result), duration=time.time() - started)

    # The adapter changes how the verdict is read, not what is checked, so a
    # fingerprint the user put on ``func`` is the adapter's too.
    fingerprint = fingerprint_of(func)
    if fingerprint is not None:
        setattr(validate, FINGERPRINT_ATTR, fingerprint)
    return validate


def merge_only_validation() -> Callable[[str], ValidationOutcome]:
    """A validator that accepts anything that merged cleanly.

    Useful as a first pass: it costs nothing and still finds every textual
    conflict, which on real branch sets is most of them.
    """

    def validate(worktree: str) -> ValidationOutcome:
        return ValidationOutcome(ok=True, stdout_tail="(merge-only: not validated)")

    # Nothing but the merge itself is inspected, and a textual conflict cannot
    # span changes that share no file. So file-overlap components genuinely do
    # combine freely here -- which is exactly the claim a whole-repo test run
    # cannot make. See `analyze(component_local=...)`.
    validate.component_local = True
    return _fingerprinted(validate, "merge-only")


def flake_tolerant(
    validate: Callable[[str], ValidationOutcome], *, retries: int = 1
) -> Callable[[str], ValidationOutcome]:
    """Re-run a failing validation ``retries`` times before believing it.

    Monotonicity is a prior, not a law, and flaky tests are the usual way it
    breaks. This is the cheap defense; the honest one is
    ``EvaluationLog.monotonicity_violations``.
    """

    def validate_with_retries(worktree: str) -> ValidationOutcome:
        outcome = validate(worktree)
        for _ in range(retries):
            if outcome.ok:
                return outcome
            outcome = validate(worktree)
        return outcome

    inner = fingerprint_of(validate)
    if inner is None:
        return validate_with_retries
    return _fingerprinted(
        validate_with_retries, "retried", inner=inner, retries=retries
    )


# --------------------------------------------------------------------------
# Staged validation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationStage:
    """One step of a staged validation.

    Args:
        name: What this step is (``setup``, ``build``, ``test``, ``lint``...).
            It ends up in the log and in the report, which is the whole point:
            "failed to build" and "tests failed" are different facts and a
            single pass/fail bit throws away the one you need.
        command: Shell command, run in the merged worktree.
        fingerprint: Optional ``worktree -> str``. When given, the stage is
            skipped if it already ran in this worktree with the same value —
            this is how an expensive dependency install is amortized across
            evaluations instead of being paid every time (keyed on, say, the
            hash of the lockfile).
        timeout: Seconds before the stage is declared failed.
        required: A failing required stage fails the whole validation and stops
            the sequence (the default). A non-required stage's failure is
            recorded in ``failing_tests`` and the set still counts as good —
            for an advisory pass, such as a lint the project runs as a separate
            CI job rather than a gate.
    """

    name: str
    command: str
    fingerprint: Optional[Callable[[str], str]] = None
    timeout: Optional[float] = None
    required: bool = True


def file_fingerprint(*paths: str) -> Callable[[str], str]:
    """A fingerprint function over the contents of the given repo-relative files.

    The canonical use is a lockfile: install dependencies again only when
    ``pnpm-lock.yaml`` actually changed between two candidate merges.
    """
    import hashlib

    def fingerprint(worktree: str) -> str:
        digest = hashlib.sha256()
        for rel in paths:
            full = os.path.join(worktree, rel)
            digest.update(rel.encode())
            if os.path.exists(full):
                with open(full, "rb") as f:
                    digest.update(f.read())
        return digest.hexdigest()[:16]

    return fingerprint


def staged_validation(
    stages: Sequence[ValidationStage],
    *,
    env: Optional[dict] = None,
    inputs: Sequence[str] = (),
) -> Callable[[str], ValidationOutcome]:
    """Run an ordered list of :class:`ValidationStage` steps, reporting which one failed.

    Real projects do not have "the test command"; they have a sequence, and the
    steps are not equally interesting. A JS repo may need
    ``pnpm install`` (slow, only when the lockfile moved), then a build (a
    *prerequisite* of testing — without it the tests do not even collect, and a
    validator that skipped it would report a false failure), then the tests,
    then a lint pass.

    The failing stage's name is prefixed onto every reported failure id, so the
    log distinguishes ``build: ...`` from ``test: tests/x.ts::y``.

    ``inputs`` names files outside the repository that any stage runs; their
    contents join the fingerprint (see :func:`inputs_digest`).
    """
    done: Dict[str, Dict[str, str]] = {}

    def validate(worktree: str) -> ValidationOutcome:
        started = time.time()
        failures: List[str] = []
        files: List[str] = []
        tail = ""
        ok = True
        runs: List[StageRun] = []
        for stage in stages:
            if stage.fingerprint is not None:
                value = stage.fingerprint(worktree)
                if done.get(worktree, {}).get(stage.name) == value:
                    runs.append(StageRun(stage.name, skipped=True))
                    continue
            stage_started = time.time()
            outcome = _run(
                [stage.command], worktree, timeout=stage.timeout, env=env, shell=True
            )
            runs.append(
                StageRun(stage.name, time.time() - stage_started, outcome.returncode)
            )
            tail = f"[{stage.name}]\n{outcome.stdout_tail}"
            if outcome.ok:
                if stage.fingerprint is not None:
                    done.setdefault(worktree, {})[stage.name] = stage.fingerprint(
                        worktree
                    )
                continue
            found = outcome.failing_tests or [f"<{stage.name} failed>"]
            failures += [f"{stage.name}: {f}" for f in found]
            files += outcome.failing_files
            if stage.required:
                ok = False
                break
            # A non-required stage is *recorded* and does not veto. Otherwise the
            # flag would be nearly pointless: an advisory lint pass would exclude
            # every change set, and a project whose lint is a separate CI job
            # could not be described at all.
        return ValidationOutcome(
            ok=ok,
            failing_tests=failures,
            failing_files=list(dict.fromkeys(files)),
            duration=time.time() - started,
            stdout_tail=tail,
            returncode=0 if ok else 1,
            stages=runs,
        )

    # A stage's own `fingerprint` is left out: it decides whether a setup step
    # that already ran in this worktree runs again, not what the verdict is.
    return _fingerprinted(
        validate,
        "staged",
        stages=[
            [
                s.name,
                s.command,
                _same_verdicts(timeout=s.timeout)["timeout"],
                s.required,
            ]
            for s in stages
        ],
        env=env,
        inputs=inputs,
    )


def js_validation(
    *,
    install: str = "pnpm install --frozen-lockfile",
    build: Optional[str] = None,
    test: str = "pnpm run test",
    lint: Optional[str] = None,
    lockfile: str = "pnpm-lock.yaml",
    timeout: Optional[float] = None,
    inputs: Sequence[str] = (),
) -> Callable[[str], ValidationOutcome]:
    """A staged validator shaped like a JavaScript project.

    Install is fingerprinted on the lockfile so it runs only when dependencies
    actually changed; the build, when given, is a required prerequisite of the
    tests rather than part of them. ``inputs``: files outside the repository
    that any step runs (see :func:`inputs_digest`).
    """
    stages = [
        ValidationStage(
            "setup", install, fingerprint=file_fingerprint(lockfile), timeout=timeout
        )
    ]
    if build:
        stages.append(ValidationStage("build", build, timeout=timeout))
    stages.append(ValidationStage("test", test, timeout=timeout))
    if lint:
        stages.append(ValidationStage("lint", lint, timeout=timeout, required=False))
    return staged_validation(stages, inputs=inputs)
