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
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from mergeset.base import CapabilityError, ValidationOutcome

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
    """

    def validate(worktree: str) -> ValidationOutcome:
        paths = list(select_paths(worktree)) if select_paths else []
        return _run(["pytest", *args, *paths], worktree, timeout=timeout, env=env)

    return validate


def command_validation(
    command: str,
    *,
    timeout: Optional[float] = None,
    env: Optional[dict] = None,
) -> Callable[[str], ValidationOutcome]:
    """A validator that runs an arbitrary shell command in the merged worktree."""

    def validate(worktree: str) -> ValidationOutcome:
        return _run([command], worktree, timeout=timeout, env=env, shell=True)

    return validate


def act_validation(
    *,
    job: Optional[str] = None,
    timeout: Optional[float] = None,
    env: Optional[dict] = None,
) -> Callable[[str], ValidationOutcome]:
    """A validator that runs the repository's GitHub Actions locally with ``act``."""

    def validate(worktree: str) -> ValidationOutcome:
        check_validation_capability(worktree, "act")
        cmd = ["act", "-q"] + (["-j", job] if job else [])
        return _run(cmd, worktree, timeout=timeout, env=env)

    return validate


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
    return validate


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

    return validate_with_retries


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
        required: A failing required stage stops the sequence (the default);
            a non-required stage is recorded and the sequence continues.
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
    stages: Sequence[ValidationStage], *, env: Optional[dict] = None
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
    """
    done: Dict[str, Dict[str, str]] = {}

    def validate(worktree: str) -> ValidationOutcome:
        started = time.time()
        failures: List[str] = []
        files: List[str] = []
        tail = ""
        ok = True
        for stage in stages:
            if stage.fingerprint is not None:
                value = stage.fingerprint(worktree)
                if done.get(worktree, {}).get(stage.name) == value:
                    continue
            outcome = _run(
                [stage.command], worktree, timeout=stage.timeout, env=env, shell=True
            )
            tail = f"[{stage.name}]\n{outcome.stdout_tail}"
            if outcome.ok:
                if stage.fingerprint is not None:
                    done.setdefault(worktree, {})[stage.name] = stage.fingerprint(
                        worktree
                    )
                continue
            ok = False
            found = outcome.failing_tests or [f"<{stage.name} failed>"]
            failures += [f"{stage.name}: {f}" for f in found]
            files += outcome.failing_files
            if stage.required:
                break
        return ValidationOutcome(
            ok=ok,
            failing_tests=failures,
            failing_files=list(dict.fromkeys(files)),
            duration=time.time() - started,
            stdout_tail=tail,
            returncode=0 if ok else 1,
        )

    return validate


def js_validation(
    *,
    install: str = "pnpm install --frozen-lockfile",
    build: Optional[str] = None,
    test: str = "pnpm run test",
    lint: Optional[str] = None,
    lockfile: str = "pnpm-lock.yaml",
    timeout: Optional[float] = None,
) -> Callable[[str], ValidationOutcome]:
    """A staged validator shaped like a JavaScript project.

    Install is fingerprinted on the lockfile so it runs only when dependencies
    actually changed; the build, when given, is a required prerequisite of the
    tests rather than part of them.
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
    return staged_validation(stages)
