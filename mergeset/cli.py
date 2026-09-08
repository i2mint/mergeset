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
from mergeset.base import CapabilityError
from mergeset.gitops import create_integration_branch
from mergeset.oracle import claude_code_resolver
from mergeset.log import EvaluationLog
from mergeset.report import html_report, markdown_report
from mergeset.sources import (
    branch_changes,
    fetch_pull_requests,
    local_branch_names,
    pr_changes,
)
from mergeset.validation import (
    command_validation,
    flake_tolerant,
    merge_only_validation,
    pytest_validation,
)


def _validator(
    *, merge_only: bool, validate_command: Optional[str], timeout: Optional[float],
    retries: int,
):
    if merge_only:
        return merge_only_validation()
    validate = (
        command_validation(validate_command, timeout=timeout)
        if validate_command
        else pytest_validation(timeout=timeout)
    )
    return flake_tolerant(validate, retries=retries) if retries else validate


def _progress(event: str, payload: dict) -> None:
    interesting = {
        "merging": lambda p: f"  merging {', '.join(p['subset'])}",
        "validating": lambda p: f"  validating {', '.join(p['subset'])}",
        "evaluated": lambda p: f"  -> {p['verdict']}: {', '.join(p['subset']) or '(empty)'}",
        "conflict": lambda p: f"  conflict: {', '.join(p['subset'])}",
        "maximal_good_set": lambda p: f"  MAXIMAL GOOD SET: {', '.join(p['subset'])}",
        "textual_conflict": lambda p: f"  textual conflict: {p['pair'][0]} x {p['pair'][1]}",
        "component": lambda p: f"component: {', '.join(p['changes'])}",
        "assisted_merge": lambda p: f"  attempting assisted resolution of {p['files']}",
    }
    render = interesting.get(event)
    if render:
        print(render(payload), file=sys.stderr, flush=True)


def _emit_reports(analysis, report_dir: Optional[str], title: str) -> list:
    written = []
    if not report_dir:
        return written
    os.makedirs(report_dir, exist_ok=True)
    md_path = os.path.join(report_dir, "REPORT.md")
    html_path = os.path.join(report_dir, "report.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_report(analysis, title=title))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_report(analysis, title=title))
    written += [md_path, html_path]
    return written


def branches(
    branch: list[str],
    *,
    repo: str = ".",
    base: str = "HEAD",
    validate_command: Optional[str] = None,
    merge_only: bool = False,
    timeout: Optional[float] = None,
    retries: int = 0,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    log_path: Optional[str] = None,
    report_dir: Optional[str] = None,
    integration_branches: bool = False,
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
        merge_only: Skip validation entirely; only textual mergeability counts.
        timeout: Seconds allowed per validation run.
        retries: Re-run a failing validation this many times before believing it.
        max_evaluations: Stop after this many expensive evaluations.
        max_seconds: Stop after this much wall time.
        max_sets: Stop after finding this many maximal sets.
        log_path: Evaluation log (JSONL). Default ``<repo>/.mergeset/evaluations.jsonl``.
        report_dir: Write ``REPORT.md`` and ``report.html`` here.
        integration_branches: Create a local ``integration/*`` branch per maximal set.
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
        repo, changes, base=base, validate_command=validate_command,
        merge_only=merge_only, timeout=timeout, retries=retries,
        max_evaluations=max_evaluations, max_seconds=max_seconds, max_sets=max_sets,
        log_path=log_path, report_dir=report_dir,
        integration_branches=integration_branches, resolver=resolver,
        no_pairwise=no_pairwise,
        no_decompose=no_decompose, quiet=quiet, title=f"mergeset — branches on {base}",
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
    merge_only: bool = False,
    timeout: Optional[float] = None,
    retries: int = 0,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    log_path: Optional[str] = None,
    report_dir: Optional[str] = None,
    integration_branches: bool = False,
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
    """
    from datetime import datetime, timedelta, timezone

    pull_requests = fetch_pull_requests(repo_spec, author=author)
    if not include_drafts:
        pull_requests = [pr for pr in pull_requests if not pr.get("isDraft")]
    if updated_within_hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=updated_within_hours)
        pull_requests = [
            pr for pr in pull_requests
            if pr.get("updatedAt")
            and datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00")) >= cutoff
        ]
    if not pull_requests:
        return "No pull requests matched the filters."
    changes = list(pr_changes(repo, pull_requests, base=base))
    return _run(
        repo, changes, base=base, validate_command=validate_command,
        merge_only=merge_only, timeout=timeout, retries=retries,
        max_evaluations=max_evaluations, max_seconds=max_seconds, max_sets=max_sets,
        log_path=log_path, report_dir=report_dir,
        integration_branches=integration_branches, resolver=resolver,
        no_pairwise=no_pairwise,
        no_decompose=no_decompose, quiet=quiet, title=f"mergeset — {repo_spec} PRs",
    )


def _run(
    repo, changes, *, base, validate_command, merge_only, timeout, retries,
    max_evaluations, max_seconds, max_sets, log_path, report_dir,
    integration_branches, resolver, no_pairwise, no_decompose, quiet, title,
) -> str:
    if resolver not in ("none", "claude"):
        return f"Unknown resolver {resolver!r}; expected 'none' or 'claude'."
    try:
        analysis = _analyze(
            repo, changes, base=base,
            validate=_validator(
                merge_only=merge_only, validate_command=validate_command,
                timeout=timeout, retries=retries,
            ),
            resolver=claude_code_resolver() if resolver == "claude" else None,
            log_path=log_path,
            pairwise_preoracle=not no_pairwise,
            decompose=not no_decompose,
            max_evaluations=max_evaluations,
            max_seconds=max_seconds,
            max_sets=max_sets,
            on_event=None if quiet else _progress,
        )
    except CapabilityError as e:
        return f"mergeset cannot run yet:\n\n{e}"
    lines = [markdown_report(analysis, title=title)]
    for path in _emit_reports(analysis, report_dir, title):
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
            analysis.repo, name, analysis.base_sha,
            [(cid, by_id[cid].head) for cid in plan["changes"]],
        )
        out.append(f"`{name}`: {'created ' + detail[:8] if created else detail}")
    return out


def show_log(*, log_path: str = ".mergeset/evaluations.jsonl") -> str:
    """Print what the evaluation log already knows, without evaluating anything."""
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
        lines.append(f"  ! monotonicity violation: {sorted(bad)} bad but {sorted(good)} good")
    return "\n".join(lines)


def report(
    *, log_path: str = ".mergeset/evaluations.jsonl", out: Optional[str] = None
) -> str:
    """Re-render reports from an existing evaluation log — no evaluation needed."""
    log = EvaluationLog(log_path)
    if not len(log):
        return f"{log_path} is empty; run `mergeset branches` or `mergeset prs` first."
    return show_log(log_path=log_path)


#: SSOT of the CLI surface. Any adapter (cw, HTTP, MCP) consumes this list.
_dispatch_funcs = [branches, prs, show_log, report]


def main() -> int:
    """Entry point: project ``_dispatch_funcs`` onto a command line parser."""
    import cw

    return cw.dispatch(_dispatch_funcs)


if __name__ == "__main__":
    raise SystemExit(main())
