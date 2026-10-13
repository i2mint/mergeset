# mergeset.cli

Command line surface.

The durable part is `_dispatch_funcs` — a plain list of plain functions. Only
the last line binds it to an adapter, so the library stays free of any CLI
library and a second surface (HTTP, MCP) is the same list projected differently.

Note the deliberate absence of `from __future__ import annotations`: it turns
every hint into a string, and the CLI adapter reads the real annotations to
decide that `--max-seconds` is a float rather than the string `"600"`.

### Module Attributes

| [`EXIT_ABORTED`](#mergeset.cli.EXIT_ABORTED)   | the report is printed and is not an answer.   |
|-----------------------------------------------------------------|-----------------------------------------------|

### Functions

| [`branches`](#mergeset.cli.branches)(branch, \*[, repo, base, ...])   | Find maximal mergeable sets among the given branches.                     |
|--------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`install_skills`](#mergeset.cli.install_skills)([target, copy, overwrite]) | Install the agent skill bundled in this package into an agent host.       |
| [`main`](#mergeset.cli.main)([argv])                              | Entry point: project `_dispatch_funcs` onto a command line parser.        |
| [`prs`](#mergeset.cli.prs)(repo_spec, \*[, repo, author, ...])   | Find maximal mergeable sets among a repository's open pull requests.      |
| [`show_log`](#mergeset.cli.show_log)(\*[, log_path, repo])            | Print what the evaluation log already knows, without evaluating anything. |

### Classes

| [`AbortedReport`](#mergeset.cli.AbortedReport)   | The report of a run that aborted.   |
|------------------------------------------------------------------|-------------------------------------|

### *class* mergeset.cli.AbortedReport

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

The report of a run that aborted. A `str` everywhere, but the CLI exits
[`EXIT_ABORTED`](#mergeset.cli.EXIT_ABORTED) on it, so a script or CI step cannot read it as a
finished run (#53).

### mergeset.cli.EXIT_ABORTED *= 3*

the
report is printed and is not an answer. 1 and 2 stay with Python and argparse.

* **Type:**
  Exit status of a run that aborted (a search met an ERROR, ADR 0036)

### mergeset.cli.branches(branch, , repo='.', base='HEAD', validate_command=None, validate_stage=None, validate_fingerprint=None, validate_optional=None, validate_input=None, merge_only=False, tier=None, tier_cost=None, timeout=None, retries=0, max_evaluations=None, max_seconds=None, max_sets=None, confirm_budget_seconds=None, confirm_max_runs=None, confirm_max_sets=None, must_include=None, log_path=None, trust_unpinned_log=False, report_dir=None, report_format=None, integration_branches=False, reuse_worktree=None, resolver='none', no_pairwise=False, no_decompose=False, quiet=False)

Find maximal mergeable sets among the given branches.

* **Parameters:**
  * **branch** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Branch names, as positional arguments.
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to the git repository.
  * **base** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What to merge onto.
  * **validate_command** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Shell command that validates a merged tree.
    Default: a fail-fast pytest run.
  * **validate_stage** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'name:command'`, repeatable, in order — the way to
    describe a project whose validation is a sequence rather than one
    command (install, then build, then test, then lint). Each stage
    reports its own exit code, so “failed to build” stays
    distinguishable from “tests failed”. Overrides –validate-command.
  * **validate_fingerprint** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'stage:path'`, repeatable — skip that stage
    unless the file’s contents changed. Point it at a lockfile and a
    slow dependency install is paid once per run instead of once per
    evaluation (pair it with –reuse-worktree).
  * **validate_optional** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – Stage name, repeatable — its failure is recorded but
    does not veto the set. Use it for a lint pass the project treats as
    advisory.
  * **validate_input** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – Path, repeatable — a file (or directory) outside the
    repository that the validation runs, such as the script in
    `--validate-command 'python ~/checks/smoke.py'`. Its contents join
    the validator’s fingerprint, so editing it retires the verdicts the
    old version gave; without it, only the command’s text counts. Files
    inside the repository need no flag: the commits pin them. Applies
    to every tier.
  * **merge_only** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Skip validation entirely; only textual mergeability counts.
  * **tier** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'name:command'`, repeatable, ordered cheapest-first — tiered
    validation: the first tier screens every candidate set, and each
    later tier only confirms the sets its predecessor left standing, so
    an expensive suite runs on a handful of sets instead of dozens. A
    tier is ONE validator with its OWN evaluation log (a cheap PASS is
    not evidence about an expensive tier). `--validate-stage`
    composes stages *inside* one validator; `--tier` composes
    validators. To make the staged validator a tier, give its name
    bare: `--validate-stage 'build:make' 'test:make test' --tier
    unit 'e2e:make e2e'`. Tier logs live in the artifact store next
    to the default log, one per tier, so –log-path is refused here.
    –tier takes every value after it: put branch names first.
  * **tier_cost** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'tier:seconds'`, repeatable — the declared cost of one
    run, used until the tier has been timed. Set it for a tier that has
    never run, or it is scheduled as if it were cheap.
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds allowed per validation run (per tier, with –tier).
  * **retries** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Re-run a failing validation this many times before believing it.
  * **max_evaluations** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Stop after this many expensive evaluations (with
    –tier, these three bound the screening tier).
  * **max_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Stop after this much wall time.
  * **max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Stop after finding this many maximal sets.
  * **confirm_budget_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – With –tier: seconds each deeper tier may
    spend. Runs are admitted on the pessimistic estimate, so the budget
    is not overrun on a guess.
  * **confirm_max_runs** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – With –tier: at most this many runs per deeper tier;
    wins over the budget when both are given.
  * **confirm_max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – With –tier: stop a deeper tier after confirming this
    many maximal sets (`1`: just the best plan, cheaply).
  * **must_include** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – Change id, repeatable (a branch name, or `pr12` for
    `prs`), with –tier — also report the best plan that keeps these
    changes. It answers a different question from the maximal sets and
    is reported alongside them, never instead. A single bare `--tier
    NAME` is enough to ask it of the ordinary validator.
  * **log_path** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Evaluation log (JSONL). Default:
    `~/.local/share/mergeset/evaluations/<repo-slug>.jsonl` —
    outside the analysed repository, always.
  * **trust_unpinned_log** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Reuse rows of an old log that predate rows
    recording their commits or their validator. Only when no head has
    moved and the validation is unchanged since.
  * **report_dir** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Write `REPORT.md` and `report.html` into this
    directory. By default they go to the artifact store
    (`<artifact root>/reports/<repo-slug>/`), never into the
    analysed repository — see [`mergeset.storage`](mergeset.storage.html.md#module-mergeset.storage).
  * **integration_branches** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Create a local `integration/*` branch per maximal set.
  * **reuse_worktree** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Absolute path to one git worktree to check every
    candidate merge out into, instead of a fresh one per evaluation.
    This is what makes a fingerprinted setup stage worth having: the
    install survives between evaluations. It is created if missing.
  * **resolver** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `none` (default) or `claude` to let a Claude Code
    subagent attempt *mechanical* conflict resolutions. Anything it
    resolves is flagged as assisted and its diff kept — never
    reported as a clean merge.
  * **no_pairwise** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Skip the `git merge-tree` pre-oracle (skipped anyway with a
    resolver, which is offered those conflicts instead).
  * **no_decompose** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Do not split into independent file-overlap components.
  * **quiet** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Suppress progress output.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.cli.install_skills(target='~/.claude/skills', , copy=False, overwrite=False)

Install the agent skill bundled in this package into an agent host.

`pip install mergeset` already ships the skill inside the package; agent
hosts read their own directory, so this links one to the other. A symlink by
default, so upgrading the package upgrades the skill; `--copy` for hosts
or filesystems that cannot follow one. An existing skill is left alone;
`--overwrite` replaces whatever is at the destination.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.cli.main(argv=None)

Entry point: project `_dispatch_funcs` onto a command line parser.

cw’s default convention stops reading a function’s annotations as soon as
it declares any parameter (argh’s rule), which would turn `--max-seconds
60` into the string `"60"`. `hints_when_declared` keeps the hints and
merges the declarations on top.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### mergeset.cli.prs(repo_spec, , repo='.', author=None, updated_within_hours=None, base=None, include_drafts=False, validate_command=None, validate_stage=None, validate_fingerprint=None, validate_optional=None, validate_input=None, merge_only=False, tier=None, tier_cost=None, timeout=None, retries=0, max_evaluations=None, max_seconds=None, max_sets=None, confirm_budget_seconds=None, confirm_max_runs=None, confirm_max_sets=None, must_include=None, log_path=None, trust_unpinned_log=False, report_dir=None, report_format=None, integration_branches=False, reuse_worktree=None, resolver='none', no_pairwise=False, no_decompose=False, quiet=False)

Find maximal mergeable sets among a repository’s open pull requests.

* **Parameters:**
  * **repo_spec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – GitHub `owner/name`.
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Local clone the PR head refs are fetched into.
  * **author** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Only PRs by this GitHub login.
  * **updated_within_hours** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Only PRs updated this recently.
  * **base** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Override the base commit; default is each PR’s own base.
  * **include_drafts** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Include draft PRs (excluded by default).
  * **validate_stage** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'name:command'`, repeatable and ordered — see
    `mergeset branches --help`.
  * **validate_fingerprint** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'stage:path'`, repeatable — skip a stage unless
    that file changed (a lockfile, typically).
  * **validate_optional** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – Stage name, repeatable — recorded, but not a veto.
  * **validate_input** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – Path, repeatable — a file outside the repository the
    validation runs; its contents join the fingerprint. See
    `mergeset branches --help`.
  * **tier** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'name:command'`, repeatable, cheapest-first — tiered validation;
    a bare name is the tier the –validate-\* flags describe. See
    `mergeset branches --help` for how tiers and stages compose.
  * **tier_cost** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – `'tier:seconds'`, repeatable — declared cost per run.
  * **confirm_budget_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – With –tier: seconds each deeper tier may spend.
  * **confirm_max_runs** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – With –tier: at most this many runs per deeper tier.
  * **confirm_max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – With –tier: stop a deeper tier after this many sets.
  * **must_include** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – PR change id (`pr12`), repeatable, with –tier — also
    report the best plan that keeps these PRs.
  * **log_path** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Evaluation log (JSONL). Default:
    `~/.local/share/mergeset/evaluations/<repo-slug>.jsonl` — outside
    the analysed repository, always.
  * **trust_unpinned_log** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Reuse rows of an old log that predate rows
    recording their commits or their validator. Only when no head has
    moved and the validation is unchanged since.
  * **report_dir** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Write `REPORT.md` and `report.html` into this directory.
    By default they go to the artifact store, under
    `reports/<repo-slug>/<timestamp>/`, so a re-run never overwrites
    the run before it.
  * **report_format** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)) – Repeatable — `markdown`, `html`, `pdf`. Default:
    markdown and html. `pdf` needs `pip install 'mergeset[pdf]'`.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.cli.show_log(, log_path=None, repo='.')

Print what the evaluation log already knows, without evaluating anything.

Use this to answer questions about a finished run: the log is the single
source of truth, so re-deriving what it already says costs a reader’s trust.
(Re-rendering the full Markdown/HTML reports needs the candidate metadata as
well as the log, so it is a library call — `markdown_report(analysis)` —
not a command that could pretend the log alone is enough.)

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
