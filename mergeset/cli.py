"""Command line surface.

The durable part is ``_dispatch_funcs`` — a plain list of plain functions. Only
the last line binds it to an adapter, so the library stays free of any CLI
library and a second surface (HTTP, MCP) is the same list projected differently.


Note the deliberate absence of ``from __future__ import annotations``: it turns
every hint into a string, and the CLI adapter reads the real annotations to
decide that ``--max-seconds`` is a float rather than the string ``"600"``.
"""

import os
import sys
from typing import Optional, Sequence

from mergeset.analysis import analyze as _analyze
from mergeset.base import CapabilityError, MergesetError
from mergeset.gitops import create_integration_branch
from mergeset.oracle import claude_code_resolver
from mergeset.log import EvaluationLog
from mergeset.report import REPORT_FORMATS, markdown_report, write_reports
from mergeset.storage import (
    artifact_store,
    evaluation_log_path,
    run_key,
    slash_separated_keys,
)
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
    return staged_validation(built)


def _validator(
    *,
    merge_only: bool,
    validate_command: Optional[str],
    timeout: Optional[float],
    retries: int,
    validate_stage: Sequence[str] = (),
    validate_fingerprint: Sequence[str] = (),
    validate_optional: Sequence[str] = (),
):
    if merge_only:
        return merge_only_validation()
    if validate_stage:
        validate = _staged(
            validate_stage, validate_fingerprint, validate_optional, timeout
        )
    elif validate_command:
        validate = command_validation(validate_command, timeout=timeout)
    else:
        validate = pytest_validation(timeout=timeout)
    return flake_tolerant(validate, retries=retries) if retries else validate


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


def branches(
    branch: list[str],
    *,
    repo: str = ".",
    base: str = "HEAD",
    validate_command: Optional[str] = None,
    validate_stage: list = None,
    validate_fingerprint: list = None,
    validate_optional: list = None,
    merge_only: bool = False,
    timeout: Optional[float] = None,
    retries: int = 0,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    log_path: Optional[str] = None,
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
        merge_only: Skip validation entirely; only textual mergeability counts.
        timeout: Seconds allowed per validation run.
        retries: Re-run a failing validation this many times before believing it.
        max_evaluations: Stop after this many expensive evaluations.
        max_seconds: Stop after this much wall time.
        max_sets: Stop after finding this many maximal sets.
        log_path: Evaluation log (JSONL). Default:
            ``~/.local/share/mergeset/evaluations/<repo-slug>.jsonl`` —
            outside the analysed repository, always.
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
        merge_only=merge_only,
        timeout=timeout,
        retries=retries,
        max_evaluations=max_evaluations,
        max_seconds=max_seconds,
        max_sets=max_sets,
        log_path=log_path,
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
    merge_only: bool = False,
    timeout: Optional[float] = None,
    retries: int = 0,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    log_path: Optional[str] = None,
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
        log_path: Evaluation log (JSONL). Default:
            ``~/.local/share/mergeset/evaluations/<repo-slug>.jsonl`` — outside
            the analysed repository, always.
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
        merge_only=merge_only,
        timeout=timeout,
        retries=retries,
        max_evaluations=max_evaluations,
        max_seconds=max_seconds,
        max_sets=max_sets,
        log_path=log_path,
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
    merge_only,
    timeout,
    retries,
    max_evaluations,
    max_seconds,
    max_sets,
    log_path,
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
    try:
        analysis = _analyze(
            repo,
            changes,
            base=base,
            validate=_validator(
                merge_only=merge_only,
                validate_command=validate_command,
                timeout=timeout,
                retries=retries,
                validate_stage=validate_stage,
                validate_fingerprint=validate_fingerprint,
                validate_optional=validate_optional,
            ),
            resolver=claude_code_resolver() if resolver == "claude" else None,
            log_path=log_path,
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
            [(cid, by_id[cid].head) for cid in plan["changes"]],
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
        lines.append(
            f"{e.verdict.value:6} {e.duration:7.1f}s  {', '.join(sorted(e.subset))}"
        )
    lines += ["", "Maximal passing sets:"]
    lines += [f"  {', '.join(sorted(s))}" for s in log.maximal_passing_sets()]
    lines += ["Minimal failing sets (conflicts):"]
    lines += [f"  {', '.join(sorted(s))}" for s in log.minimal_failing_sets()]
    for good, bad in log.monotonicity_violations():
        lines.append(
            f"  ! monotonicity violation: {sorted(bad)} bad but {sorted(good)} good"
        )
    return "\n".join(lines)


#: SSOT of the CLI surface. Any adapter (cw, HTTP, MCP) consumes this list.
_dispatch_funcs = [branches, prs, show_log]


def main() -> int:
    """Entry point: project ``_dispatch_funcs`` onto a command line parser."""
    import cw

    return cw.dispatch(_dispatch_funcs)


if __name__ == "__main__":
    raise SystemExit(main())
