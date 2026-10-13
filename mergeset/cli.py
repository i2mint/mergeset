"""Command line surface.

The durable part is ``_dispatch_funcs`` — a plain list of plain functions. Only
the last line binds it to an adapter, so the library stays free of any CLI
library and a second surface (HTTP, MCP) is the same list projected differently.


Note the deliberate absence of ``from __future__ import annotations``: it turns
every hint into a string, and the CLI adapter reads the real annotations to
decide that ``--max-seconds`` is a float rather than the string ``"600"``.
"""

import math
import os
import re
import sys
from typing import Optional, Sequence

from mergeset.analysis import analyze as _analyze
from mergeset.base import CapabilityError, MergesetError
from mergeset.gitops import create_integration_branch, git
from mergeset.oracle import claude_code_resolver
from mergeset.log import EvaluationLog
from mergeset.report import (
    REPORT_FORMATS,
    markdown_report,
    stage_breakdown,
    write_reports,
)
from mergeset.tiers import Tier, analyze_tiered as _analyze_tiered
from mergeset.storage import (
    artifact_store,
    evaluation_log_path,
    run_key,
    slash_separated_keys,
)
from mergeset.skills import install_skills as _install_skills
from mergeset.sources import (
    branch_changes,
    fetch_pull_requests,
    local_branch_names,
    pr_changes,
)
from mergeset.validation import (
    ValidationStage,
    command_validation,
    file_fingerprint,
    flake_tolerant,
    merge_only_validation,
    pytest_validation,
    staged_validation,
)


def _split_pair(spec: str, flag: str) -> tuple:
    """``'name:value'`` -> ``('name', 'value')``, with a usable error otherwise."""
    name, sep, value = spec.partition(":")
    if not sep or not name.strip() or not value.strip():
        raise ValueError(
            f"{flag} expects 'name:value', got {spec!r}. "
            f"For example: {flag} 'test:pnpm run test'"
        )
    return name.strip(), value.strip()


def _staged(
    stages: Sequence[str],
    fingerprints: Sequence[str],
    optional: Sequence[str],
    timeout: Optional[float],
    inputs: Sequence[str] = (),
):
    """Build a staged validator from the repeatable CLI flags.

    This is what lets the CLI reach a real project. A single shell string can
    chain the same commands, but it throws away everything that matters: the
    setup stage stops being skippable (so a dependency install is paid on every
    evaluation), build and test failures collapse into one exit code, and a lint
    pass the project treats as advisory becomes a veto.
    """
    stage_names = [_split_pair(spec, "--validate-stage")[0] for spec in stages]
    fingerprint_paths = dict(
        _split_pair(f, "--validate-fingerprint") for f in fingerprints
    )
    optional_names = {name.strip() for name in optional}
    for label, names in (
        ("--validate-fingerprint", set(fingerprint_paths)),
        ("--validate-optional", optional_names),
    ):
        unknown = names - set(stage_names)
        if unknown:
            raise ValueError(
                f"{label} names no stage: {', '.join(sorted(unknown))}. "
                f"Declared stages are: {', '.join(stage_names) or '(none)'}."
            )
    built = []
    for spec in stages:
        name, command = _split_pair(spec, "--validate-stage")
        path = fingerprint_paths.get(name)
        built.append(
            ValidationStage(
                name,
                command,
                fingerprint=file_fingerprint(path) if path else None,
                timeout=timeout,
                required=name not in optional_names,
            )
        )
    return staged_validation(built, inputs=inputs)


def _validator(
    *,
    merge_only: bool,
    validate_command: Optional[str],
    timeout: Optional[float],
    retries: int,
    validate_stage: Sequence[str] = (),
    validate_fingerprint: Sequence[str] = (),
    validate_optional: Sequence[str] = (),
    validate_input: Sequence[str] = (),
):
    if merge_only:
        return merge_only_validation()
    if validate_stage:
        validate = _staged(
            validate_stage,
            validate_fingerprint,
            validate_optional,
            timeout,
            inputs=validate_input,
        )
    elif validate_command:
        validate = command_validation(
            validate_command, timeout=timeout, inputs=validate_input
        )
    else:
        validate = pytest_validation(timeout=timeout, inputs=validate_input)
    return flake_tolerant(validate, retries=retries) if retries else validate


#: What a bare ``--tier NAME`` may look like. Anything with a space in it is far
#: more likely a ``name:command`` that lost its colon than a name.
_BARE_TIER = re.compile(r"^[\w.-]+$")

#: Flags that only mean something across tiers, by the keyword the CLI uses.
_TIER_ONLY_FLAGS = {
    "tier_cost": "--tier-cost",
    "confirm_budget_seconds": "--confirm-budget-seconds",
    "confirm_max_runs": "--confirm-max-runs",
    "confirm_max_sets": "--confirm-max-sets",
    "must_include": "--must-include",
}

#: Flags that describe the one validator a bare ``--tier NAME`` stands for.
_VALIDATOR_FLAGS = {
    "validate_command": "--validate-command",
    "validate_stage": "--validate-stage",
    "validate_fingerprint": "--validate-fingerprint",
    "validate_optional": "--validate-optional",
    "merge_only": "--merge-only",
}


def _tiers(
    specs: Sequence[str],
    costs: Sequence[str],
    *,
    validator,
    validator_flags: Sequence[str],
    timeout: Optional[float],
    retries: int,
    inputs: Sequence[str] = (),
    is_commit=lambda name: False,
) -> list:
    """Build the ordered tiers from ``--tier`` and ``--tier-cost``.

    ``'name:command'`` is a tier that runs one shell command. A bare ``name`` is
    the tier the ordinary validation flags describe (``--validate-stage`` and
    friends, or the default pytest run), which is how a staged validator becomes
    one rung: the stages compose *inside* a tier, the tiers compose *across*
    validators, each with its own log. At most one tier can be bare, since there
    is only one set of validation flags. ``'name:'`` (empty command) is the same
    bare tier, spelled so that it cannot be mistaken for anything else.
    ``inputs`` (``--validate-input``) joins every tier's fingerprint: a file a
    tier does not run only costs that tier a re-run when it changes.
    """
    tiers, bare = [], []
    for spec in specs:
        name, sep, command = spec.partition(":")
        explicit_bare = bool(sep) and not command.strip()
        if sep and not explicit_bare:
            name, command = _split_pair(spec, "--tier")
            validate = command_validation(command, timeout=timeout, inputs=inputs)
            if retries:
                validate = flake_tolerant(validate, retries=retries)
        else:
            name = name.strip()
            if not _BARE_TIER.match(name):
                raise ValueError(
                    f"--tier expects 'name:command', or a bare name for the tier "
                    f"the --validate-* flags describe; got {spec!r}. For example: "
                    "--tier 'unit:pytest -x' 'e2e:pnpm run e2e'"
                )
            if not explicit_bare and is_commit(name):
                # `--tier` takes every value after it, so a branch, tag or sha
                # typed after the flag lands here instead of among the
                # candidates -- and would silently run as a tier.
                raise ValueError(
                    f"`{name}` names a commit in this repository, so it reads as "
                    "a branch that followed --tier rather than a tier. Put the "
                    f"branch names before --tier. If `{name}` really is the "
                    f"tier's name, spell it --tier '{name}:'."
                )
            bare.append(name)
            validate = validator
        tiers.append(Tier(name, validate))
    if len(bare) > 1:
        raise ValueError(
            f"Only one --tier can be a bare name ({', '.join(bare)} are); a bare "
            "tier is the one validator the --validate-* flags describe. Give the "
            "others a command: --tier 'name:command'."
        )
    if validator_flags and not bare:
        # Without a bare tier these flags would describe a validator no tier
        # runs, and dropping an option in silence is worse than refusing it.
        raise ValueError(
            f"{', '.join(validator_flags)} describe one validator, but no tier "
            "runs it. Name the tier it is with a bare --tier NAME, e.g. "
            "--validate-stage 'build:make' 'test:make test' --tier unit "
            "'e2e:make e2e'."
        )
    declared = {}
    for spec in costs:
        name, value = _split_pair(spec, "--tier-cost")
        try:
            seconds = float(value)
        except ValueError:
            seconds = -1.0
        if not (seconds > 0 and math.isfinite(seconds)):
            raise ValueError(
                f"--tier-cost expects 'name:seconds' with finite seconds > 0, "
                f"got {spec!r}."
            )
        if name in declared:
            raise ValueError(f"--tier-cost names `{name}` twice.")
        declared[name] = seconds
    unknown = set(declared) - {t.name for t in tiers}
    if unknown:
        raise ValueError(
            f"--tier-cost names no tier: {', '.join(sorted(unknown))}. Declared "
            f"tiers are: {', '.join(t.name for t in tiers)}."
        )
    return [Tier(t.name, t.validate, cost=declared.get(t.name)) for t in tiers]


def _progress(event: str, payload: dict) -> None:
    interesting = {
        "merging": lambda p: f"  merging {', '.join(p['subset']) or '(base alone)'}",
        "validating": lambda p: f"  validating {', '.join(p['subset'])}",
        # A cache hit costs nothing; printing it makes a free re-run look like
        # minutes of work, and the shrink walks over the same set repeatedly.
        "evaluated": lambda p: (
            None
            if p.get("cached")
            else f"  -> {p['verdict']}: {', '.join(p['subset']) or '(base alone)'}"
        ),
        "conflict": lambda p: f"  conflict: {', '.join(p['subset'])}",
        "maximal_good_set": lambda p: f"  MAXIMAL GOOD SET: {', '.join(p['subset'])}",
        "textual_conflict": lambda p: (
            f"  textual conflict: {p['pair'][0]} x {p['pair'][1]}"
        ),
        "component": lambda p: f"component: {', '.join(p['changes'])}",
        "assisted_merge": lambda p: f"  attempting assisted resolution of {p['files']}",
        "tier": lambda p: f"tier {p['name']} ({p['role']})",
        "tier_skipped": lambda p: f"  tier {p['name']} skipped: {p['why']}",
        "anytime": lambda p: f"  anytime: {p['summary']}",
    }
    render = interesting.get(event)
    if render:
        line = render(payload)
        if line:  # a renderer returns None for events not worth a line
            print(line, file=sys.stderr, flush=True)


def _persistent_worktree(repo: str, base: Optional[str], path: str) -> str:
    """Create the reusable worktree if it is not there yet, and return its path."""
    from mergeset.gitops import persistent_worktree

    return persistent_worktree(
        repo, base or "HEAD", os.path.abspath(os.path.expanduser(path))
    )


def _emit_reports(
    analysis,
    report_dir: Optional[str],
    title: str,
    *,
    formats: Sequence[str] = ("markdown", "html"),
    reports=None,
    run: Optional[str] = None,
) -> list:
    """Write the run's reports and return where they went.

    Naming and placement live in :func:`mergeset.report.write_reports`, so the
    CLI cannot drift from the library on where a report goes. ``report_dir`` is
    the explicit override for "put it right here", and it does overwrite,
    because that is what naming a directory asks for.
    """
    if report_dir:
        text_store, binary_store = (
            _dir_store(report_dir),
            _dir_store(report_dir, binary=True),
        )
        key = ""
    else:
        text_store, binary_store, key = reports, None, run or run_key(analysis.repo)

    written = write_reports(
        analysis,
        title=title,
        formats=formats,
        key=key,
        reports=text_store,
        binary_reports=binary_store,
    )
    store = text_store if text_store is not None else artifact_store("reports")
    return [_where(store, k) for k in written.values()]


def _dir_store(directory: str, *, binary: bool = False):
    """A store rooted at an explicit directory — ``str`` values, or ``bytes``."""
    from dol import Files, TextFiles, mk_dirs_if_missing

    os.makedirs(directory, exist_ok=True)
    # Same slash rule as the artifact store: one key namespace, every platform.
    cls = Files if binary else TextFiles
    return slash_separated_keys(mk_dirs_if_missing(cls(directory)))


def _where(store, key: str) -> str:
    """A human-facing location for ``key`` — a real path when there is one.

    Keys are always ``/``-separated; a path on this platform may not be, so the
    key is translated rather than concatenated.
    """
    rootdir = getattr(store, "rootdir", None)
    if not isinstance(rootdir, str):
        return key
    return os.path.join(rootdir, *key.split("/"))


def _repeatable(*params: str):
    """Make these list flags accumulate across repeats.

    argparse's default for a ``nargs='*'`` option keeps only the *last* use, so
    ``--tier a:x --tier b:y`` would silently be one tier. ``extend`` makes it
    two, and ``--tier a:x b:y`` still works. Declared through cw's plain
    ``_cw`` attribute, so this module still imports no CLI library (``main``
    keeps the type hints on, which a declaration would otherwise switch off).
    """
    params = {p: {"action": "extend", "nargs": "*"} for p in params}

    def mark(func):
        func._cw = {"params": params}
        return func

    return mark


_LIST_FLAGS = (
    "validate_stage",
    "validate_fingerprint",
    "validate_optional",
    "validate_input",
    "tier",
    "tier_cost",
    "must_include",
    "report_format",
)


@_repeatable(*_LIST_FLAGS)
def branches(
    branch: list[str],
    *,
    repo: str = ".",
    base: str = "HEAD",
    validate_command: Optional[str] = None,
    validate_stage: list = None,
    validate_fingerprint: list = None,
    validate_optional: list = None,
    validate_input: list = None,
    merge_only: bool = False,
    tier: list = None,
    tier_cost: list = None,
    timeout: Optional[float] = None,
    retries: int = 0,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    confirm_budget_seconds: Optional[float] = None,
    confirm_max_runs: Optional[int] = None,
    confirm_max_sets: Optional[int] = None,
    must_include: list = None,
    log_path: Optional[str] = None,
    trust_unpinned_log: bool = False,
    report_dir: Optional[str] = None,
    report_format: list = None,
    integration_branches: bool = False,
    reuse_worktree: Optional[str] = None,
    resolver: str = "none",
    no_pairwise: bool = False,
    no_decompose: bool = False,
    quiet: bool = False,
) -> str:
    """Find maximal mergeable sets among the given branches.

    Args:
        branch: Branch names, as positional arguments.
        repo: Path to the git repository.
        base: What to merge onto.
        validate_command: Shell command that validates a merged tree.
            Default: a fail-fast pytest run.
        validate_stage: ``'name:command'``, repeatable, in order — the way to
            describe a project whose validation is a sequence rather than one
            command (install, then build, then test, then lint). Each stage
            reports its own exit code, so "failed to build" stays
            distinguishable from "tests failed". Overrides --validate-command.
        validate_fingerprint: ``'stage:path'``, repeatable — skip that stage
            unless the file's contents changed. Point it at a lockfile and a
            slow dependency install is paid once per run instead of once per
            evaluation (pair it with --reuse-worktree).
        validate_optional: Stage name, repeatable — its failure is recorded but
            does not veto the set. Use it for a lint pass the project treats as
            advisory.
        validate_input: Path, repeatable — a file (or directory) outside the
            repository that the validation runs, such as the script in
            ``--validate-command 'python ~/checks/smoke.py'``. Its contents join
            the validator's fingerprint, so editing it retires the verdicts the
            old version gave; without it, only the command's text counts. Files
            inside the repository need no flag: the commits pin them. Applies
            to every tier.
        merge_only: Skip validation entirely; only textual mergeability counts.
        tier: ``'name:command'``, repeatable, ordered cheapest-first — tiered
            validation: the first tier screens every candidate set, and each
            later tier only confirms the sets its predecessor left standing, so
            an expensive suite runs on a handful of sets instead of dozens. A
            tier is ONE validator with its OWN evaluation log (a cheap PASS is
            not evidence about an expensive tier). ``--validate-stage``
            composes stages *inside* one validator; ``--tier`` composes
            validators. To make the staged validator a tier, give its name
            bare: ``--validate-stage 'build:make' 'test:make test' --tier
            unit 'e2e:make e2e'``. Tier logs live in the artifact store next
            to the default log, one per tier, so --log-path is refused here.
            --tier takes every value after it: put branch names first.
        tier_cost: ``'tier:seconds'``, repeatable — the declared cost of one
            run, used until the tier has been timed. Set it for a tier that has
            never run, or it is scheduled as if it were cheap.
        timeout: Seconds allowed per validation run (per tier, with --tier).
        retries: Re-run a failing validation this many times before believing it.
        max_evaluations: Stop after this many expensive evaluations (with
            --tier, these three bound the screening tier).
        max_seconds: Stop after this much wall time.
        max_sets: Stop after finding this many maximal sets.
        confirm_budget_seconds: With --tier: seconds each deeper tier may
            spend. Runs are admitted on the pessimistic estimate, so the budget
            is not overrun on a guess.
        confirm_max_runs: With --tier: at most this many runs per deeper tier;
            wins over the budget when both are given.
        confirm_max_sets: With --tier: stop a deeper tier after confirming this
            many maximal sets (``1``: just the best plan, cheaply).
        must_include: Change id, repeatable (a branch name, or ``pr12`` for
            ``prs``), with --tier — also report the best plan that keeps these
            changes. It answers a different question from the maximal sets and
            is reported alongside them, never instead. A single bare ``--tier
            NAME`` is enough to ask it of the ordinary validator.
        log_path: Evaluation log (JSONL). Default:
            ``~/.local/share/mergeset/evaluations/<repo-slug>.jsonl`` —
            outside the analysed repository, always.
        trust_unpinned_log: Reuse rows of an old log that predate rows
            recording their commits or their validator. Only when no head has
            moved and the validation is unchanged since.
        report_dir: Write ``REPORT.md`` and ``report.html`` into this
            directory. By default they go to the artifact store
            (``<artifact root>/reports/<repo-slug>/``), never into the
            analysed repository — see :mod:`mergeset.storage`.
        integration_branches: Create a local ``integration/*`` branch per maximal set.
        reuse_worktree: Absolute path to one git worktree to check every
            candidate merge out into, instead of a fresh one per evaluation.
            This is what makes a fingerprinted setup stage worth having: the
            install survives between evaluations. It is created if missing.
        resolver: ``none`` (default) or ``claude`` to let a Claude Code
            subagent attempt *mechanical* conflict resolutions. Anything it
            resolves is flagged as assisted and its diff kept — never
            reported as a clean merge.
        no_pairwise: Skip the `git merge-tree` pre-oracle.
        no_decompose: Do not split into independent file-overlap components.
        quiet: Suppress progress output.
    """
    changes = list(branch_changes(repo, branch, base=base))
    return _run(
        repo,
        changes,
        base=base,
        validate_command=validate_command,
        validate_stage=validate_stage or (),
        validate_fingerprint=validate_fingerprint or (),
        validate_optional=validate_optional or (),
        validate_input=validate_input or (),
        merge_only=merge_only,
        tier=tier,
        tier_cost=tier_cost,
        timeout=timeout,
        retries=retries,
        max_evaluations=max_evaluations,
        max_seconds=max_seconds,
        max_sets=max_sets,
        confirm_budget_seconds=confirm_budget_seconds,
        confirm_max_runs=confirm_max_runs,
        confirm_max_sets=confirm_max_sets,
        must_include=must_include,
        log_path=log_path,
        trust_unpinned_log=trust_unpinned_log,
        report_dir=report_dir,
        report_format=tuple(report_format) if report_format else None,
        integration_branches=integration_branches,
        reuse_worktree=reuse_worktree,
        resolver=resolver,
        no_pairwise=no_pairwise,
        no_decompose=no_decompose,
        quiet=quiet,
        title=f"mergeset — branches on {base}",
    )


@_repeatable(*_LIST_FLAGS)
def prs(
    repo_spec: str,
    *,
    repo: str = ".",
    author: Optional[str] = None,
    updated_within_hours: Optional[float] = None,
    base: Optional[str] = None,
    include_drafts: bool = False,
    validate_command: Optional[str] = None,
    validate_stage: list = None,
    validate_fingerprint: list = None,
    validate_optional: list = None,
    validate_input: list = None,
    merge_only: bool = False,
    tier: list = None,
    tier_cost: list = None,
    timeout: Optional[float] = None,
    retries: int = 0,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    confirm_budget_seconds: Optional[float] = None,
    confirm_max_runs: Optional[int] = None,
    confirm_max_sets: Optional[int] = None,
    must_include: list = None,
    log_path: Optional[str] = None,
    trust_unpinned_log: bool = False,
    report_dir: Optional[str] = None,
    report_format: list = None,
    integration_branches: bool = False,
    reuse_worktree: Optional[str] = None,
    resolver: str = "none",
    no_pairwise: bool = False,
    no_decompose: bool = False,
    quiet: bool = False,
) -> str:
    """Find maximal mergeable sets among a repository's open pull requests.

    Args:
        repo_spec: GitHub ``owner/name``.
        repo: Local clone the PR head refs are fetched into.
        author: Only PRs by this GitHub login.
        updated_within_hours: Only PRs updated this recently.
        base: Override the base commit; default is each PR's own base.
        include_drafts: Include draft PRs (excluded by default).
        validate_stage: ``'name:command'``, repeatable and ordered — see
            ``mergeset branches --help``.
        validate_fingerprint: ``'stage:path'``, repeatable — skip a stage unless
            that file changed (a lockfile, typically).
        validate_optional: Stage name, repeatable — recorded, but not a veto.
        validate_input: Path, repeatable — a file outside the repository the
            validation runs; its contents join the fingerprint. See
            ``mergeset branches --help``.
        tier: ``'name:command'``, repeatable, cheapest-first — tiered validation;
            a bare name is the tier the --validate-* flags describe. See
            ``mergeset branches --help`` for how tiers and stages compose.
        tier_cost: ``'tier:seconds'``, repeatable — declared cost per run.
        confirm_budget_seconds: With --tier: seconds each deeper tier may spend.
        confirm_max_runs: With --tier: at most this many runs per deeper tier.
        confirm_max_sets: With --tier: stop a deeper tier after this many sets.
        must_include: PR change id (``pr12``), repeatable, with --tier — also
            report the best plan that keeps these PRs.
        log_path: Evaluation log (JSONL). Default:
            ``~/.local/share/mergeset/evaluations/<repo-slug>.jsonl`` — outside
            the analysed repository, always.
        trust_unpinned_log: Reuse rows of an old log that predate rows
            recording their commits or their validator. Only when no head has
            moved and the validation is unchanged since.
        report_dir: Write ``REPORT.md`` and ``report.html`` into this directory.
            By default they go to the artifact store, under
            ``reports/<repo-slug>/<timestamp>/``, so a re-run never overwrites
            the run before it.
        report_format: Repeatable — ``markdown``, ``html``, ``pdf``. Default:
            markdown and html. ``pdf`` needs ``pip install 'mergeset[pdf]'``.
    """
    from datetime import datetime, timedelta, timezone

    pull_requests = fetch_pull_requests(repo_spec, author=author)
    if not include_drafts:
        pull_requests = [pr for pr in pull_requests if not pr.get("isDraft")]
    if updated_within_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=updated_within_hours)
        pull_requests = [
            pr
            for pr in pull_requests
            if pr.get("updatedAt")
            and datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00")) >= cutoff
        ]
    if not pull_requests:
        return "No pull requests matched the filters."
    changes = list(pr_changes(repo, pull_requests, base=base))
    return _run(
        repo,
        changes,
        base=base,
        validate_command=validate_command,
        validate_stage=validate_stage or (),
        validate_fingerprint=validate_fingerprint or (),
        validate_optional=validate_optional or (),
        validate_input=validate_input or (),
        merge_only=merge_only,
        tier=tier,
        tier_cost=tier_cost,
        timeout=timeout,
        retries=retries,
        max_evaluations=max_evaluations,
        max_seconds=max_seconds,
        max_sets=max_sets,
        confirm_budget_seconds=confirm_budget_seconds,
        confirm_max_runs=confirm_max_runs,
        confirm_max_sets=confirm_max_sets,
        must_include=must_include,
        log_path=log_path,
        trust_unpinned_log=trust_unpinned_log,
        report_dir=report_dir,
        report_format=tuple(report_format) if report_format else None,
        integration_branches=integration_branches,
        reuse_worktree=reuse_worktree,
        resolver=resolver,
        no_pairwise=no_pairwise,
        no_decompose=no_decompose,
        quiet=quiet,
        title=f"mergeset — {repo_spec} PRs",
    )


def _run(
    repo,
    changes,
    *,
    base,
    validate_command,
    validate_stage,
    validate_fingerprint,
    validate_optional,
    validate_input,
    merge_only,
    tier,
    tier_cost,
    timeout,
    retries,
    max_evaluations,
    max_seconds,
    max_sets,
    confirm_budget_seconds,
    confirm_max_runs,
    confirm_max_sets,
    must_include,
    log_path,
    trust_unpinned_log,
    report_dir,
    report_format,
    integration_branches,
    reuse_worktree,
    resolver,
    no_pairwise,
    no_decompose,
    quiet,
    title,
) -> str:
    if resolver not in ("none", "claude"):
        return f"Unknown resolver {resolver!r}; expected 'none' or 'claude'."
    given = locals()
    try:
        validate = _validator(
            merge_only=merge_only,
            validate_command=validate_command,
            timeout=timeout,
            retries=retries,
            validate_stage=validate_stage,
            validate_fingerprint=validate_fingerprint,
            validate_optional=validate_optional,
            validate_input=validate_input,
        )
        candidates = {c.id for c in changes}
        missing = [
            p
            for p in validate_input
            if not os.path.exists(os.path.expanduser(p))
            or p in candidates
            or (
                not os.path.isabs(os.path.expanduser(p))
                and git(repo, "rev-parse", "--verify", "--quiet", f"{p}^{{commit}}").ok
            )
        ]
        if missing:
            # `--validate-input` takes every value after it, so a branch typed
            # after it lands here and silently leaves the candidates.
            raise ValueError(
                f"--validate-input names no file, or names a branch: "
                f"{', '.join(missing)}. It takes every value after it, so put "
                "branch names before it; it names files outside the repository "
                "that the validation runs (give a path that is also a branch "
                "name as ./name or an absolute path)."
            )
        if validate_input and merge_only and not tier:
            # Merge-only runs nothing, so the files would be read and ignored.
            raise ValueError(
                "--validate-input names files a validation runs, but --merge-only "
                "runs none. Drop one of them."
            )
        for kw, values in (
            ("tier", tier),
            ("tier_cost", tier_cost),
            ("must_include", must_include),
        ):
            if values is not None and not values:
                flag = "--" + kw.replace("_", "-")
                raise ValueError(
                    f"{flag} was given no values. Drop it, or pass at least one "
                    f"(see --help)."
                )
        for kw in ("confirm_budget_seconds", "confirm_max_runs", "confirm_max_sets"):
            if given[kw] is not None and given[kw] < 0:
                raise ValueError(
                    f"{_TIER_ONLY_FLAGS[kw]} cannot be negative (got {given[kw]})."
                )
        unknown_formats = set(report_format or ()) - set(REPORT_FORMATS)
        if unknown_formats:
            # Checked before the run, not when the reports are written after
            # it: a branch name typed after --report-format lands here.
            raise ValueError(
                f"--report-format names no format: "
                f"{', '.join(sorted(unknown_formats))}. Formats are: "
                f"{', '.join(REPORT_FORMATS)}. Put branch names before it."
            )
        if not tier:
            # `is not None`, not truthiness: `--confirm-max-runs 0` is an
            # instruction, and ignoring it would be the silent drop.
            stray = [
                flag for kw, flag in _TIER_ONLY_FLAGS.items() if given[kw] is not None
            ]
            if stray:
                raise ValueError(
                    f"{', '.join(stray)} only mean something with --tier. To ask "
                    "them of the ordinary validator, make it the one tier: "
                    "--tier NAME (a bare name)."
                )
        else:
            unknown = set(must_include or ()) - {c.id for c in changes}
            if unknown:
                raise ValueError(
                    f"--must-include names changes that are not candidates: "
                    f"{', '.join(sorted(unknown))}. The candidates are: "
                    f"{', '.join(sorted(c.id for c in changes)) or '(none)'}."
                )
        if tier and log_path:
            raise ValueError(
                "--log-path cannot be used with --tier: each tier keeps its own "
                "evaluation log, and one path would merge them into the one "
                "shared cache this design exists to prevent. The tier logs sit "
                "next to the default log, one file per tier."
            )
        common = dict(
            base=base,
            resolver=claude_code_resolver() if resolver == "claude" else None,
            trust_unpinned=trust_unpinned_log,
            reuse_worktree=(
                _persistent_worktree(repo, base, reuse_worktree)
                if reuse_worktree
                else None
            ),
            pairwise_preoracle=not no_pairwise,
            decompose=not no_decompose,
            max_evaluations=max_evaluations,
            max_seconds=max_seconds,
            max_sets=max_sets,
            on_event=None if quiet else _progress,
        )
        if tier:
            tiered = _analyze_tiered(
                repo,
                changes,
                tiers=_tiers(
                    tier,
                    tier_cost or (),
                    validator=validate,
                    validator_flags=[
                        flag for kw, flag in _VALIDATOR_FLAGS.items() if given[kw]
                    ],
                    timeout=timeout,
                    retries=retries,
                    inputs=validate_input,
                    is_commit=lambda name: (
                        name in {c.id for c in changes}
                        or git(
                            repo,
                            "rev-parse",
                            "--verify",
                            "--quiet",
                            f"{name}^{{commit}}",
                        ).ok
                    ),
                ),
                confirm_budget_seconds=confirm_budget_seconds,
                confirm_max_runs=confirm_max_runs,
                confirm_max_sets=confirm_max_sets,
                must_include=must_include or (),
                **common,
            )
            analysis = tiered.analysis
            # Into the notes, so every report format carries the price list,
            # not only this command's stdout.
            analysis.notes.extend(tiered.cost_lines())
        else:
            analysis = _analyze(
                repo, changes, validate=validate, log_path=log_path, **common
            )
    except ValueError as e:
        return f"mergeset could not read that option:\n\n{e}"
    except CapabilityError as e:
        return f"mergeset cannot run yet:\n\n{e}"
    except MergesetError as e:
        # A refusal is a result, not a crash: it deserves the same shape of
        # message as any other, not a traceback with the reason at the bottom.
        return f"mergeset refused to run:\n\n{e}"
    lines = [markdown_report(analysis, title=title)]
    for path in _emit_reports(
        analysis, report_dir, title, formats=report_format or ("markdown", "html")
    ):
        lines.append(f"\nWrote {path}")
    if integration_branches:
        lines.append("\n## Integration branches\n")
        for path in _integration_branches(analysis):
            lines.append(f"- {path}")
    return "\n".join(lines)


def _integration_branches(analysis) -> list:
    from datetime import date

    by_id = analysis.by_id
    out = []
    for plan in analysis.merge_plan():
        name = f"integration/{date.today().isoformat()}-{plan['rank']}"
        created, detail = create_integration_branch(
            analysis.repo,
            name,
            analysis.base_sha,
            # The shas that were validated, not the refs: a branch that moved
            # since would put unvalidated commits on the integration branch.
            [
                (cid, analysis.head_shas.get(cid, by_id[cid].head))
                for cid in plan["changes"]
            ],
        )
        out.append(f"`{name}`: {'created ' + detail[:8] if created else detail}")
    return out


def show_log(*, log_path: Optional[str] = None, repo: str = ".") -> str:
    """Print what the evaluation log already knows, without evaluating anything.

    Use this to answer questions about a finished run: the log is the single
    source of truth, so re-deriving what it already says costs a reader's trust.
    (Re-rendering the full Markdown/HTML reports needs the candidate metadata as
    well as the log, so it is a library call — ``markdown_report(analysis)`` —
    not a command that could pretend the log alone is enough.)
    """
    log_path = log_path or evaluation_log_path(repo)
    log = EvaluationLog(log_path)
    lines = [f"{len(log)} evaluations in {log_path}", ""]
    for e in log:
        on = f"@{e.base_sha[:8]}" if e.base_sha else "@unpinned"
        lines.append(
            f"{e.verdict.value:6} {e.duration:7.1f}s {on:9}  "
            f"{', '.join(sorted(e.subset))}"
        )
        if stage_breakdown(e):
            lines.append(f"{'':26}{stage_breakdown(e)}")
    moved = _moved_commits(log)
    if moved:
        lines += [
            "",
            "! The rows below are about different commits or validators ("
            + "; ".join(moved)
            + "), so the sets mix answers to different questions. A run of "
            "`branches`/`prs` pins the log to the current heads and uses only "
            "the rows that match them.",
        ]
    lines += ["", "Maximal passing sets:"]
    lines += [f"  {', '.join(sorted(s))}" for s in log.maximal_passing_sets()]
    lines += ["Minimal failing sets (conflicts):"]
    lines += [f"  {', '.join(sorted(s))}" for s in log.minimal_failing_sets()]
    for good, bad in log.monotonicity_violations():
        lines.append(
            f"  ! monotonicity violation: {sorted(bad)} bad but {sorted(good)} good"
        )
    return "\n".join(lines)


def _moved_commits(log) -> list:
    """What makes the log's rows disagree about commits, one phrase each."""
    bases = {e.base_sha for e in log if e.base_sha}
    heads: dict = {}
    for e in log:
        for cid, sha in e.heads.items():
            heads.setdefault(cid, set()).add(sha)
    out = [f"{len(bases)} bases"] if len(bases) > 1 else []
    out += [
        f"{cid} at {len(shas)} heads"
        for cid, shas in sorted(heads.items())
        if len(shas) > 1
    ]
    # Rows recording no validator count as one more: a mix of old rows and
    # fingerprinted ones is a mix too.
    validators = {e.validator for e in log}
    if len(validators) > 1:
        out.append(f"{len(validators)} validators")
    unpinned = sum(1 for e in log if not e.pinned)
    if unpinned and (bases or heads):
        out.append(f"{unpinned} rows record no commits")
    return out


def install_skills(
    target: str = "~/.claude/skills", *, copy: bool = False, overwrite: bool = False
) -> str:
    """Install the agent skill bundled in this package into an agent host.

    ``pip install mergeset`` already ships the skill inside the package; agent
    hosts read their own directory, so this links one to the other. A symlink by
    default, so upgrading the package upgrades the skill; ``--copy`` for hosts
    or filesystems that cannot follow one. An existing skill is left alone;
    ``--overwrite`` replaces whatever is at the destination.
    """
    try:
        installed = _install_skills(target, link=not copy, overwrite=overwrite)
    except MergesetError as e:
        # Same shape as every other refusal here: a message, not a traceback.
        return f"mergeset refused to install:\n\n{e}"
    if not installed:
        return f"Already installed in {target} (nothing to do)."
    return "Installed:\n" + "\n".join(f"  {p}" for p in installed)


#: SSOT of the CLI surface. Any adapter (cw, HTTP, MCP) consumes this list.
_dispatch_funcs = [branches, prs, show_log, install_skills]


def main(argv=None) -> int:
    """Entry point: project ``_dispatch_funcs`` onto a command line parser.

    cw's default convention stops reading a function's annotations as soon as
    it declares any parameter (argh's rule), which would turn ``--max-seconds
    60`` into the string ``"60"``. ``hints_when_declared`` keeps the hints and
    merges the declarations on top.
    """
    import dataclasses

    import cw

    convention = dataclasses.replace(cw.ARGH, hints_when_declared=True)
    return cw.dispatch(_dispatch_funcs, argv=argv, convention=convention)


if __name__ == "__main__":
    raise SystemExit(main())
