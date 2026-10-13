# mergeset.cli

Command line surface.

The durable part is `_dispatch_funcs` — a plain list of plain functions. Only
the last line binds it to an adapter, so the library stays free of any CLI
library and a second surface (HTTP, MCP) is the same list projected differently.

Note the deliberate absence of `from __future__ import annotations`: it turns
every hint into a string, and the CLI adapter reads the real annotations to
decide that `--max-seconds` is a float rather than the string `"600"`.

### Functions

| [`branches`](#mergeset.cli.branches)(branch, \*[, repo, base, ...])   | Find maximal mergeable sets among the given branches.                     |
|--------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`install_skills`](#mergeset.cli.install_skills)([target, copy, overwrite]) | Install the agent skill bundled in this package into an agent host.       |
| [`main`](#mergeset.cli.main)()                                    | Entry point: project `_dispatch_funcs` onto a command line parser.        |
| [`prs`](#mergeset.cli.prs)(repo_spec, \*[, repo, author, ...])   | Find maximal mergeable sets among a repository's open pull requests.      |
| [`show_log`](#mergeset.cli.show_log)(\*[, log_path, repo])            | Print what the evaluation log already knows, without evaluating anything. |

### mergeset.cli.branches(branch, , repo='.', base='HEAD', validate_command=None, validate_stage=None, validate_fingerprint=None, validate_optional=None, merge_only=False, timeout=None, retries=0, max_evaluations=None, max_seconds=None, max_sets=None, log_path=None, report_dir=None, report_format=None, integration_branches=False, reuse_worktree=None, resolver='none', no_pairwise=False, no_decompose=False, quiet=False)

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
  * **merge_only** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Skip validation entirely; only textual mergeability counts.
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds allowed per validation run.
  * **retries** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Re-run a failing validation this many times before believing it.
  * **max_evaluations** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Stop after this many expensive evaluations.
  * **max_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Stop after this much wall time.
  * **max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Stop after finding this many maximal sets.
  * **log_path** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Evaluation log (JSONL). Default:
    `~/.local/share/mergeset/evaluations/<repo-slug>.jsonl` —
    outside the analysed repository, always.
  * **report_dir** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Write `REPORT.md` and `report.html` into this
    directory. By default they go to the artifact store
    (`<artifact root>/reports/<repo-slug>/`), never into the
    analysed repository — see [`mergeset.storage`](mergeset.storage.md#module-mergeset.storage).
  * **integration_branches** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Create a local `integration/*` branch per maximal set.
  * **reuse_worktree** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Absolute path to one git worktree to check every
    candidate merge out into, instead of a fresh one per evaluation.
    This is what makes a fingerprinted setup stage worth having: the
    install survives between evaluations. It is created if missing.
  * **resolver** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `none` (default) or `claude` to let a Claude Code
    subagent attempt *mechanical* conflict resolutions. Anything it
    resolves is flagged as assisted and its diff kept — never
    reported as a clean merge.
  * **no_pairwise** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Skip the `git merge-tree` pre-oracle.
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

### mergeset.cli.main()

Entry point: project `_dispatch_funcs` onto a command line parser.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### mergeset.cli.prs(repo_spec, , repo='.', author=None, updated_within_hours=None, base=None, include_drafts=False, validate_command=None, validate_stage=None, validate_fingerprint=None, validate_optional=None, merge_only=False, timeout=None, retries=0, max_evaluations=None, max_seconds=None, max_sets=None, log_path=None, report_dir=None, report_format=None, integration_branches=False, reuse_worktree=None, resolver='none', no_pairwise=False, no_decompose=False, quiet=False)

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
  * **log_path** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Evaluation log (JSONL). Default:
    `~/.local/share/mergeset/evaluations/<repo-slug>.jsonl` — outside
    the analysed repository, always.
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
