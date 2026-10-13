# mergeset

Which of these branches can be merged together?

Given a base commit and *n* candidate changes (branches, PRs, commits),
`mergeset` finds the **maximal sets** that merge cleanly and still pass
validation — and the minimal **conflicts** that stop the rest.

The simple case is one call:

```default
from mergeset import analyze, branch_changes, markdown_report

changes = list(branch_changes('.', ['feature-a', 'feature-b'], base='main'))
analysis = analyze('.', changes)
print(markdown_report(analysis))
```

Everything expensive is cached in an append-only JSONL log, so a second run
costs nothing for sets already decided, and the cheap oracles (per-change CI
status, `git merge-tree` textual conflicts, file-overlap decomposition) run
first so that most answers never cost a test run at all.

Every piece is one keyword argument away from being replaced: where changes come
from (`mergeset.sources`), how a set is merged and validated
(`mergeset.oracle`, `mergeset.validation`), how the search spends its budget
(`mergeset.solve`), how results are rendered (`mergeset.report`), and where
artifacts are kept (`mergeset.storage`).

Everything mergeset produces — reports, evaluation logs, captured validation
output, fixtures — is derived from whatever repository was analysed, so it goes
to an artifact store rooted at `~/.local/share/mergeset/<kind>/` and **never**
into a repository. Point that store at S3 with one keyword argument; no caller
changes.

### Functions

| [`analyze`](#mergeset.analyze)(repo, changes, \*[, base, validate, ...])   | Find the maximal sets of `changes` that merge and validate on `base`.                                                      |
|------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| [`skills_dir`](#mergeset.skills_dir)()                                        | The directory of skills bundled inside the installed package.                                                              |
| [`install_skills`](#mergeset.install_skills)([target, skills_root, link, ...])    | Put the bundled skills where an agent host will find them.                                                                 |
| [`bundled_skills`](#mergeset.bundled_skills)([skills_root])                       | Yield the directory of every bundled skill (each holding a `SKILL.md`).                                                    |
| [`analyze_tiered`](#mergeset.analyze_tiered)(repo, changes, \*, tiers[, ...])     | Screen with the cheap tier, confirm the frontier with the expensive ones.                                                  |
| [`anytime_answer`](#mergeset.anytime_answer)(change_ids, conflicts, \*, ...)      | The best validated set so far, plus a sound bound on what is being missed.                                                 |
| [`best_set_including`](#mergeset.best_set_including)(change_ids, evaluate, \*, ...)   | The heaviest validated set that **contains** every change in `must_include`.                                               |
| [`chained_evaluate`](#mergeset.chained_evaluate)(evaluators)                        | Compose per-tier evaluators into one, short-circuiting on the first failure.                                               |
| [`tier_lines`](#mergeset.tier_lines)(repo, tier, \*[, store])                 | The append-only lines object backing one tier's evaluation log.                                                            |
| [`cost_from_log`](#mergeset.cost_from_log)(log, \*, tier[, declared, ...])       | Seed a cost model from an existing evaluation log — the real default.                                                      |
| [`set_cost`](#mergeset.set_cost)(cost_model, tiers, subset, \*[, ...])      | What it costs to take `subset` all the way down `tiers`.                                                                   |
| [`change_set`](#mergeset.change_set)(ids)                                     | Normalize any iterable of change ids into a `frozenset`.                                                                   |
| [`set_key`](#mergeset.set_key)(ids)                                        | A stable, hashable, JSON-friendly key for a change set.                                                                    |
| [`branch_changes`](#mergeset.branch_changes)(repo, branches, \*[, base, prefix])  | Changes from local or remote branches.                                                                                     |
| [`commit_changes`](#mergeset.commit_changes)(repo, commits, \*[, base])           | Changes from an explicit list of commit-ishes, one change per commit.                                                      |
| [`pr_changes`](#mergeset.pr_changes)(repo, pull_requests, \*[, base, ...])    | Turn `gh pr list` records into changes.                                                                                    |
| [`fetch_pull_requests`](#mergeset.fetch_pull_requests)(repo_spec, \*[, author, ...])   | Raw `gh pr list` records for `repo_spec` (`owner/name`).                                                                   |
| [`local_branch_names`](#mergeset.local_branch_names)(repo, \*[, pattern, exclude])    | Local branch names, optionally filtered by a glob `pattern`.                                                               |
| [`detect_stacks`](#mergeset.detect_stacks)(changes)                              | Map change id -> the change id it is stacked on, for PR stacks.                                                            |
| [`pytest_validation`](#mergeset.pytest_validation)(\*[, args, timeout, env, ...])    | A validator that runs the project's pytest suite, fail-fast by default.                                                    |
| [`command_validation`](#mergeset.command_validation)(command, \*[, timeout, env])     | A validator that runs an arbitrary shell command in the merged worktree.                                                   |
| [`act_validation`](#mergeset.act_validation)(\*[, job, timeout, env])             | A validator that runs the repository's GitHub Actions locally with `act`.                                                  |
| [`callable_validation`](#mergeset.callable_validation)(func)                           | Adapt a plain user callable into a validator.                                                                              |
| [`merge_only_validation`](#mergeset.merge_only_validation)()                             | A validator that accepts anything that merged cleanly.                                                                     |
| [`flake_tolerant`](#mergeset.flake_tolerant)(validate, \*[, retries])             | Re-run a failing validation `retries` times before believing it.                                                           |
| [`staged_validation`](#mergeset.staged_validation)(stages, \*[, env])                | Run an ordered list of [`ValidationStage`](#mergeset.ValidationStage) steps, reporting which one failed. |
| [`js_validation`](#mergeset.js_validation)(\*[, install, build, test, ...])      | A staged validator shaped like a JavaScript project.                                                                       |
| [`file_fingerprint`](#mergeset.file_fingerprint)(\*paths)                           | A fingerprint function over the contents of the given repo-relative files.                                                 |
| [`tips`](#mergeset.tips)(subset, parents)                               | The members of `subset` that nothing else in `subset` is stacked on.                                                       |
| [`close_down`](#mergeset.close_down)(subset, parents)                         | Add every ancestor, so the set becomes a valid thing to ask for.                                                           |
| [`close_up`](#mergeset.close_up)(subset, parents)                           | Add every descendant — what dropping these changes actually costs.                                                         |
| [`largest_closed_subset`](#mergeset.largest_closed_subset)(subset, parents)              | Drop members whose ancestors are missing — the set you can actually merge.                                                 |
| [`cone_weights`](#mergeset.cone_weights)(weights, parents)                      | Re-weight each change by the cost of dropping its whole descendant cone.                                                   |
| [`ancestors`](#mergeset.ancestors)(change, parents)                          | Every change `change` is stacked on, transitively.                                                                         |
| [`descendants`](#mergeset.descendants)(change, parents)                        | Every change stacked on `change`, transitively — its *cone*.                                                               |
| [`count_closed_subsets`](#mergeset.count_closed_subsets)(parents, changes)              | How many downward-closed subsets exist — the size of the real search space.                                                |
| [`git_oracle`](#mergeset.git_oracle)(repo, base, changes, \*[, ...])          | Build the evaluator: merge the set onto `base`, then validate the tree.                                                    |
| [`merge_order`](#mergeset.merge_order)(subset, changes)                        | A deterministic merge order for a change set.                                                                              |
| [`claude_code_resolver`](#mergeset.claude_code_resolver)(\*[, timeout, command])        | Resolve conflicts with a Claude Code subagent, under a strict policy.                                                      |
| [`find_maximal_good_sets`](#mergeset.find_maximal_good_sets)(changes, evaluate, \*)       | Enumerate maximal good subsets of `changes`, cheapest-dropped first.                                                       |
| [`quickxplain`](#mergeset.quickxplain)(evaluate, candidates, \*[, ...])        | Shrink a known-bad set to one minimal conflict, in O(k log n) evaluations.                                                 |
| [`minimal_hitting_sets`](#mergeset.minimal_hitting_sets)(conflicts, \*[, weight, ...])  | Yield minimal hitting sets of `conflicts`, cheapest total weight first.                                                    |
| [`independent_components`](#mergeset.independent_components)(changes, files_of)           | Split changes into groups that cannot possibly interact via files.                                                         |
| [`combine_components`](#mergeset.combine_components)(per_component)                   | Cartesian-combine per-component maximal sets into global ones.                                                             |
| [`textual_conflict`](#mergeset.textual_conflict)(repo, base, head_a, head_b)        | Conflicting files if merging both heads onto `base` clashes textually.                                                     |
| [`pairwise_textual_conflicts`](#mergeset.pairwise_textual_conflicts)(repo, base, heads)       | Yield `(id_a, id_b, files)` for every pair that conflicts textually.                                                       |
| [`singleton_textual_conflicts`](#mergeset.singleton_textual_conflicts)(repo, base, heads)      | Yield `(id, files)` for every change that will not even merge onto base.                                                   |
| [`changed_files`](#mergeset.changed_files)(repo, base, head)                     | Files a change touches, as `git diff --name-only base...head`.                                                             |
| [`merge_sequence`](#mergeset.merge_sequence)(repo, base, heads)                   | Merge every head onto `base`, one at a time, without any worktree.                                                         |
| [`merged_worktree`](#mergeset.merged_worktree)(repo, base, heads, \*[, ...])       | Materialize `base` plus every head in a worktree, ready for validation.                                                    |
| [`persistent_worktree`](#mergeset.persistent_worktree)(repo, base, path)               | Create (once) a worktree meant to be reused across many evaluations.                                                       |
| [`create_integration_branch`](#mergeset.create_integration_branch)(repo, name, base, ...)    | Create a local branch holding `base` + all heads, for manual testing.                                                      |
| [`markdown_report`](#mergeset.markdown_report)(analysis, \*[, title])              | Render the analysis as Markdown.                                                                                           |
| [`html_report`](#mergeset.html_report)(analysis, \*[, title])                  | Render the analysis as one self-contained HTML file.                                                                       |
| [`artifact_store`](#mergeset.artifact_store)(kind, \*[, rootdir, ...])            | A store for one kind of artifact — `str` values, or `bytes`.                                                               |
| [`artifact_mall`](#mergeset.artifact_mall)(\*[, rootdir, store_factory, ...])    | All the artifact stores, keyed by kind — a *mall*, in `dol` terms.                                                         |
| [`artifact_path`](#mergeset.artifact_path)(kind[, key, rootdir, app_name])       | Filesystem path for `kind`/`key` under the *local* artifact root.                                                          |
| [`app_data_rootdir`](#mergeset.app_data_rootdir)(\*[, app_name, envvar])            | The artifact root for `app_name`, honouring `$MERGESET_DATA_DIR`.                                                          |
| [`evaluation_log_path`](#mergeset.evaluation_log_path)(repo, \*[, rootdir, app_name])  | Default evaluation-log path for `repo` — in the artifact store.                                                            |
| [`evaluation_lines`](#mergeset.evaluation_lines)(repo, \*[, store, rootdir, ...])   | The append-only lines object backing this repo's evaluation log.                                                           |
| [`run_key`](#mergeset.run_key)(repo, \*[, at])                             | A key naming one run of one repository: `<repo-slug>/<timestamp>`.                                                         |
| [`slash_separated_keys`](#mergeset.slash_separated_keys)(store, \*[, sep])              | Make `/` the key separator whatever the platform's is.                                                                     |

### Classes

| [`Analysis`](#mergeset.Analysis)(repo, base, base_sha, changes[, ...])    | Everything a run learned.                                                                             |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| [`TieredAnalysis`](#mergeset.TieredAnalysis)(tiers, analysis, logs, cost_model) | Result of a tiered run.                                                                               |
| [`Tier`](#mergeset.Tier)(name, validate[, cost, available])           | One rung of validation, from cheapest to dearest.                                                     |
| [`AnytimeAnswer`](#mergeset.AnytimeAnswer)(best, best_weight, best_tier, ...)  | The best answer so far, and how much better an answer could still be.                                 |
| [`CostModel`](#mergeset.CostModel)(\*args, \*\*kwargs)                     | What the scheduler needs to know about price.                                                         |
| [`MeasuredCost`](#mergeset.MeasuredCost)([declared, per_change, ...])         | A per-tier cost model fitted to observations, backed by declarations.                                 |
| [`Change`](#mergeset.Change)(id, head, base[, source, weight, meta])    | One candidate change: everything between `base` and `head`.                                           |
| [`ChangeSet`](#mergeset.ChangeSet)                                         |                                                                                                       |
| [`Evaluation`](#mergeset.Evaluation)(subset, verdict[, stage, merge, ...])  | One row of the evaluation log — the single source of truth.                                           |
| [`Verdict`](#mergeset.Verdict)(\*values)                                 | Outcome of evaluating a change set.                                                                   |
| [`MergeOutcome`](#mergeset.MergeOutcome)(ok[, reason, ...])                   | Result of merging a change set onto its base.                                                         |
| [`ValidationOutcome`](#mergeset.ValidationOutcome)(ok[, failing_tests, ...])       | Result of validating a merged tree.                                                                   |
| [`StageRun`](#mergeset.StageRun)(name[, duration, returncode, skipped])   | What one stage of a staged validation did, and what it cost.                                          |
| [`EvaluationLog`](#mergeset.EvaluationLog)([store, pins, trust_unpinned])      | Append-only record of evaluations, plus the monotone closure over it.                                 |
| [`JsonlLines`](#mergeset.JsonlLines)(path)                                  | Append-only sequence of JSON objects backed by one file.                                              |
| [`MemoryLines`](#mergeset.MemoryLines)([iterable])                           | In-memory stand-in for [`JsonlLines`](#mergeset.JsonlLines) (tests, dry runs). |
| [`ValidationStage`](#mergeset.ValidationStage)(name, command[, ...])             | One step of a staged validation.                                                                      |
| [`StoreLines`](#mergeset.StoreLines)(store, key)                            | Lines backed by one key of a `MutableMapping` — the non-file backend.                                 |

### Exceptions

| [`MergesetError`](#mergeset.MergesetError)   | Base class for errors this package raises deliberately.                    |
|------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`CapabilityError`](#mergeset.CapabilityError) | A required external capability is missing; the message says how to fix it. |

### *class* mergeset.Analysis(repo, base, base_sha, changes, head_shas=<factory>, maximal_sets=<factory>, conflicts=<factory>, textual_conflicts=<factory>, components=<factory>, files_by_change=<factory>, stacks=<factory>, merged_through=<factory>, weights=<factory>, own_weights=<factory>, singleton_conflicts=<factory>, components_combined=False, unverified_sets=<factory>, log=None, searches=<factory>, notes=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Everything a run learned. Every field is derivable from `log` + git.

#### *property* by_id *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Change](mergeset.base.html.md#mergeset.base.Change)]*

Changes keyed by id.

#### components_combined *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

Whether the per-component answers were trusted to combine, or whether a
global search had to verify them. See `analyze(component_local=...)`.

#### *property* evaluations *: [int](https://docs.python.org/3/builtins/functions.html#int)*

How many expensive evaluations this analysis rests on.

Counted from the **log**, which is the source of truth, not from the
search state, which only knows what *this process* ran. Regenerating a
report from a complete log spends nothing, and the search-state number
then reads 0 — so the better the cache worked, the more the archived
report understated the work. A real 18-candidate run that cost 9
evaluations and 344 s reported “0 expensive evaluations spent”.

Rows are counted when they decided something about this candidate set:
a recorded PASS or FAIL (an ERROR established nothing) over a subset of
the changes in play (so an older run’s rows for a different candidate
set in the same log are not claimed as this analysis’s work). The base
check counts — it is an evaluation, and on a real project it is one of
the slowest.

#### *property* evaluations_this_run *: [int](https://docs.python.org/3/builtins/functions.html#int)*

How many expensive evaluations *this process* spent.

The number a progress display wants — 0 on a re-run is correct here and
misleading in a report. See [`evaluations`](#mergeset.Analysis.evaluations).

#### *property* exhausted *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff every component’s search finished rather than hit a budget.

#### head_shas *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

Full head sha of each change, resolved once at the start. Everything that
merges uses these, never the refs, so what is recorded is what was merged.

#### merge_plan()

One entry per maximal set: what to merge, in what order, what it drops.

This is the deliverable — “merge these, in this order, and you lose these”.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### merged_through *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

The `stacks` edges whose child head really contains the parent’s head,
so merging the child brings the parent along. Only these let the oracle
merge a tip alone; any other parent is merged explicitly, or the row
would name a parent head that was never in the tree (#23).

#### own_weights *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

Cost of the change on its own, before the cone is accounted for.

#### *property* pinned_changes *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Change](mergeset.base.html.md#mergeset.base.Change)]*

The changes with `head` replaced by the sha it resolved to.

A branch that moves mid-run must not have its new commits merged under
a row pinned to the old ones; merging the resolved shas rules that out.

#### singleton_conflicts *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [List](https://docs.python.org/3/library/typing.html#typing.List)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]]*

Changes that will not even merge onto base alone -> conflicting files.

#### unverified_sets *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

Sets reported without ever having been evaluated as a whole. Empty is the
normal case. See [`merge_plan()`](#mergeset.Analysis.merge_plan)’s `verified` and ADR 0025.

#### weights *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

Cost of dropping each change *including its descendant cone*.

### *class* mergeset.AnytimeAnswer(best, best_weight, best_tier, full_depth, bound, bound_set, gap, optimal, pending=(), spent=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The best answer so far, and how much better an answer could still be.

`bound` is a genuine upper bound, not a hope. Every conflict — found at
any tier, by any pre-oracle — refutes a real set, so the heaviest set that
no known conflict forbids is the heaviest set that *could* still pass. Its
weight is therefore an upper bound on the optimum, and `gap` is what is
still unknown.

`gap <= 0` together with full tier depth is a **certificate**: the
heaviest set nothing refutes has itself been validated, so nothing better
exists. That is a stopping rule rather than a budget running out.

#### best

Heaviest set validated so far, at `best_tier`.

#### best_weight

Its weight (the sum of its changes’ weights).

#### best_tier

Deepest tier that actually ran on `best`; `None` when
nothing has been validated yet.

#### full_depth

True iff every tier ran on `best`. When False, `best` is
a partial claim however good `gap` looks.

### bound, bound_set

The upper bound and the set that realizes it.

#### gap

`bound - best_weight` — what might still be being missed.

#### optimal

`gap <= 0 and full_depth`; nothing better exists.

#### pending

`(set, estimated seconds to confirm)` for candidates not yet
taken to full depth. The answer to “what would closing the gap
cost”.

#### spent

Seconds spent, per tier.

#### summary()

One line a progress display or a report can print.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> AnytimeAnswer(frozenset({'a'}), 1.0, 'unit', False, 2.0,
...               frozenset({'a', 'b'}), 1.0, False).summary()
'best 1 change (weight 1.0, confirmed to tier `unit`); bound 2.0; gap 1.0'
>>> AnytimeAnswer(frozenset({'a', 'b'}), 2.0, 'e2e', True, 2.0,
...               frozenset({'a', 'b'}), 0.0, True).summary()
'best 2 changes (weight 2.0, all tiers); provably maximal'
```

### *exception* mergeset.CapabilityError

Bases: [`MergesetError`](mergeset.base.html.md#mergeset.base.MergesetError)

A required external capability is missing; the message says how to fix it.

### *class* mergeset.Change(id, head, base, source='branch', weight=None, meta=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One candidate change: everything between `base` and `head`.

* **Parameters:**
  * **id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Short stable identifier, used everywhere else (log, report, CLI).
  * **head** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Commit-ish holding the change (branch name, sha, PR head).
  * **base** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Commit-ish the change is measured against.
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Which source produced it (`'branch'`, `'pr'`, `'commit'`).
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Cost of *dropping* this change. The solver drops the cheapest
    changes it can when it must drop something, so a high weight means
    “keep me”. `None` means “let the weighting policy decide”.
  * **meta** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]) – Source-specific extras (PR number, author, CI status, draft flag…).

```pycon
>>> c = Change(id='fix-a', head='origin/fix-a', base='origin/main')
>>> c.id, c.source
('fix-a', 'branch')
```

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.Change.to_jdict).

* **Return type:**
  [`Change`](mergeset.base.html.md#mergeset.base.Change)

#### to_jdict()

JSON-able view of the change.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### with_weight(weight)

A copy of this change carrying `weight`.

* **Return type:**
  [`Change`](mergeset.base.html.md#mergeset.base.Change)

### mergeset.ChangeSet

alias of [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

### *class* mergeset.CostModel(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

What the scheduler needs to know about price.

Any object with these four methods is a cost model: a table of declared
constants, a model fitted to the log, or something that queries a CI
provider’s historical timings.

#### estimate(tier, subset)

Central estimate, in seconds. Used to *order* candidate work.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### is_measured(tier)

Whether this tier’s estimate rests on observation or on a guess.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### observe(tier, subset, seconds)

Record what an evaluation cost, so the next estimate is better.

`seconds` is a total, or a per-stage mapping that is summed.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### pessimistic(tier, subset)

Upper estimate, in seconds. Used to *admit* work against a budget.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### *class* mergeset.Evaluation(subset, verdict, stage=None, merge=None, validation=None, duration=0.0, at=None, note='', base_sha=None, heads=<factory>, validator=None, cached=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One row of the evaluation log — the single source of truth.

Everything else (conflict set, known-good/known-bad closure, merge plan,
reports) is *derived* from a sequence of these and is re-derivable.

A row is about the commits that were actually merged, not about the ids:
`base_sha` and `heads` (change id -> head sha) pin it to them, so a row
written before a branch was rewritten is never mistaken for an answer about
the rewritten branch (i2mint/mergeset#23). Rows written before pinning
existed carry neither and read back as *unpinned*; see
[`mergeset.log.EvaluationLog`](mergeset.log.html.md#mergeset.log.EvaluationLog). `validator` pins it to what was run
on that tree, the same way (i2mint/mergeset#32): the same commits under a
different test command are a different question.

#### base_sha *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

Full sha of the base the set was merged onto. `None` on unpinned rows.

#### cached *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

True when this came from the log rather than from a real run. Not
serialized: it is a fact about *this* lookup, not about the evaluation.

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.Evaluation.to_jdict).

* **Return type:**
  [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)

#### heads *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

Full head sha of each change in `subset` when it was evaluated.

#### *property* ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the set evaluated as good.

#### *property* pinned *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff the row records which commits it was evaluated against.

#### to_jdict()

JSON-able view; `subset` becomes a sorted list.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### validator *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

Fingerprint of the validator that judged the tree (see
[`mergeset.validation.fingerprint_of()`](mergeset.validation.html.md#mergeset.validation.fingerprint_of)). `None` on rows written
before fingerprints, and on rows judged by a validator that has none.

### *class* mergeset.EvaluationLog(store=None, , pins=None, trust_unpinned=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Append-only record of evaluations, plus the monotone closure over it.

* **Parameters:**
  * **store** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – Persistence seam. A path (str/PathLike) is wrapped in
    [`JsonlLines`](#mergeset.JsonlLines); pass [`StoreLines`](#mergeset.StoreLines) to put the log in an
    artifact store (S3 and friends), or [`MemoryLines`](#mergeset.MemoryLines) for an
    ephemeral log. With no argument at all the log goes to the artifact
    store’s `evaluations/adhoc.jsonl` — never the working directory.
  * **pins** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Pins`](mergeset.log.html.md#mergeset.log.Pins)]) – The commits the questions are about (see `Pins` and
    [`pin()`](#mergeset.EvaluationLog.pin)). Unpinned, every row counts, as before pinning existed;
    [`mergeset.analyze()`](#mergeset.analyze) always pins.
  * **trust_unpinned** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Let rows that record no commits at all (written before
    i2mint/mergeset#23, or by an unpinned log), or no validator while
    the pins name one (written before i2mint/mergeset#32), count as
    matches once the log is pinned. Off by default, because such a row
    may be about a head that has since moved, or judged by a command
    that has since changed — which is the defect pinning exists to
    close. Turn it on only when you know neither has changed since those
    rows were written; it is the migration path for an old log. A row
    whose recorded commits or validator differ never counts.

```pycon
>>> log = EvaluationLog(MemoryLines())
>>> from mergeset.base import Evaluation, Verdict
>>> _ = log.record(Evaluation(frozenset({'a', 'b'}), Verdict.PASS))
>>> bool(log.known(frozenset({'a'})))          # subset of a passing set
True
>>> log.known(frozenset({'a'})).verdict.value
'pass'
>>> _ = log.record(Evaluation(frozenset({'c', 'd'}), Verdict.FAIL))
>>> log.known(frozenset({'a', 'c', 'd'})).verdict.value   # superset of a failing set
'fail'
>>> log.known(frozenset({'a', 'c'})).verdict is None
True
```

#### caching(evaluate, , infer_pass=True)

Wrap `evaluate` so known sets are answered from the log.

The returned callable is what the solver should be handed: it never
spends a real evaluation on a set the log can already decide.

`infer_pass=False` runs a set whose PASS would only be *inferred*
from a passing superset, and records it: for a caller that needs an
exact PASS behind every claim (a cheaper tier on the way to a deeper
one). Exact rows and inferred FAILs are still answered from the log.

```pycon
>>> log = EvaluationLog(MemoryLines())
>>> _ = log.record(Evaluation(frozenset('ab'), Verdict.PASS))
>>> runs = []
>>> def run(s):
...     runs.append(set_key(s))
...     return Evaluation(s, Verdict.PASS)
>>> log.caching(run)(frozenset('a')).cached, runs
(True, [])
>>> log.caching(run, infer_pass=False)(frozenset('a')).cached, runs
(False, [('a',)])
```

#### exact(subset)

The most recent evaluation of exactly this set, if any.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]

#### *property* failing *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

Sets recorded as bad, smallest first (smallest are the most useful).

#### known(subset)

What we know about `subset` without evaluating it.

Exact hits win; otherwise the monotone closure decides, preferring the
cheapest witness (the largest passing superset, the smallest failing
subset).

* **Return type:**
  [`Known`](mergeset.log.html.md#mergeset.log.Known)

#### maximal_passing_sets()

Recorded passing sets with no recorded passing proper superset.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

#### minimal_failing_sets()

Recorded failing sets with no recorded failing proper subset.

These are the *conflicts* the solver hits. They are minimal with respect
to what has been observed, which is not necessarily globally minimal —
the solver shrinks them further with QuickXplain as it goes.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

#### monotonicity_violations()

`(good, bad)` pairs where a *subset* of a good set was seen failing.

A non-empty result means the downward-closure assumption broke here:
a flaky test, a non-deterministic build, or a change that *fixes*
another. Reported, never silently smoothed over.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]]

#### *property* other_validator *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Evaluation](mergeset.base.html.md#mergeset.base.Evaluation)]*

The [`stale`](#mergeset.EvaluationLog.stale) rows judged by a validator other than the pinned one.

Usually a tier or `--validate-command` whose command was edited.

#### *property* passing *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

Sets recorded as good, largest first.

#### pin(, base, heads, validator=None)

Scope *this* log to `base`, these heads and `validator`; returns `self`.

`validator` is the fingerprint of what the questions will be asked of
([`mergeset.validation.fingerprint_of()`](mergeset.validation.html.md#mergeset.validation.fingerprint_of)); `None` matches rows on
commits alone.

[`pinned()`](#mergeset.EvaluationLog.pinned) is the same without changing this object.

From here on, reading ([`known()`](#mergeset.EvaluationLog.known), [`exact()`](#mergeset.EvaluationLog.exact), the closure,
iteration, `len`) sees only rows evaluated against these commits, and
[`record()`](#mergeset.EvaluationLog.record) stamps new rows with them. Nothing is removed: the other
rows stay in the store and in [`rows`](#mergeset.EvaluationLog.rows), and are reported by
[`stale`](#mergeset.EvaluationLog.stale) and [`unpinned`](#mergeset.EvaluationLog.unpinned).

* **Return type:**
  [`EvaluationLog`](mergeset.log.html.md#mergeset.log.EvaluationLog)

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> log = EvaluationLog(MemoryLines()).pin(base='B', heads={'a': 'A1'})
>>> _ = log.record(Evaluation(frozenset('a'), Verdict.PASS))
>>> log.known(frozenset('a')).verdict.value
'pass'
>>> _ = log.pin(base='B', heads={'a': 'A2'})   # branch a was rewritten
>>> log.known(frozenset('a')).verdict is None, len(log.rows), len(log.stale)
(True, 1, 1)
```

#### pinned(, base, heads, validator=None, trust_unpinned=None)

A view of this log scoped to `base`, these heads and `validator`.

Same store, same rows; this log itself is left as it was, so a caller
that hands one log to two analyses keeps its own view of it.

* **Return type:**
  [`EvaluationLog`](mergeset.log.html.md#mergeset.log.EvaluationLog)

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> log = EvaluationLog(MemoryLines())
>>> view = log.pinned(base='B', heads={'a': 'A1'})
>>> _ = view.record(Evaluation(frozenset('a'), Verdict.PASS))
>>> log.pins is None, len(log), len(view)
(True, 1, 1)
>>> len(log.pinned(base='B', heads={'a': 'A2'}))
0
```

#### record(evaluation)

Append `evaluation` and return it.

`at` is stamped if absent, and so are the pinned commits: a row that
does not say what it was run against cannot be told apart from one
about a branch that has since been rewritten.

* **Return type:**
  [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)

#### *property* rows *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Evaluation](mergeset.base.html.md#mergeset.base.Evaluation)]*

Every row in the log, matching the pins or not, in log order.

#### *property* stale *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Evaluation](mergeset.base.html.md#mergeset.base.Evaluation)]*

Rows evaluated against other commits, or by another validator.

Not wrong — about a different question — so kept, and not matched.

#### *property* trust_unpinned *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether rows recording no commits count once the log is pinned.

#### *property* unpinned *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Evaluation](mergeset.base.html.md#mergeset.base.Evaluation)]*

Rows recording too little to match that a pinned log is not counting.

No commits (written before #23), or no validator while the pins name
one (written before #32). All of them by default; with
`trust_unpinned`, only those holding a change that is not in play.
Empty when the log is unpinned.

### *class* mergeset.JsonlLines(path)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Append-only sequence of JSON objects backed by one file.

The default persistence seam of [`EvaluationLog`](#mergeset.EvaluationLog). Any object with
`append(jdict)` and `__iter__() -> Iterable[jdict]` can replace it (an
in-memory list, a `dol` store, a database table).

```pycon
>>> import tempfile, os
>>> path = os.path.join(tempfile.mkdtemp(), 'x.jsonl')
>>> lines = JsonlLines(path)
>>> lines.append({'a': 1}); lines.append({'a': 2})
>>> [d['a'] for d in lines]
[1, 2]
```

#### append(jdict)

Append one record, flushing immediately (crash-safe enough).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* mergeset.MeasuredCost(declared=<factory>, per_change=<factory>, unmeasured_seconds=60.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A per-tier cost model fitted to observations, backed by declarations.

* **Parameters:**
  * **declared** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `tier -> seconds`, used until that tier has been observed.
    This is how a tier nobody has ever run gets a sane price: the person
    adding it usually knows roughly what it costs.
  * **per_change** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `change id -> extra seconds` this change adds to any
    evaluation containing it. The per-change half of the model, for the
    case where one candidate is known to be much heavier than the rest.
    Default: nothing, and the fitted slope carries the average
    per-change cost instead.
  * **unmeasured_seconds** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Price of a tier with neither observations nor a
    declaration. See `UNMEASURED_TIER_SECONDS`.

```pycon
>>> cost = MeasuredCost(declared={'e2e': 300.0})
>>> cost.estimate('e2e', frozenset({'a'}))
300.0
>>> cost.is_measured('e2e')
False
>>> cost.observe('unit', frozenset({'a'}), 10.0)
>>> cost.observe('unit', frozenset({'a', 'b', 'c'}), 20.0)
>>> cost.observe('unit', frozenset({'a', 'b', 'c', 'd', 'e'}), 30.0)
>>> cost.estimate('unit', frozenset({'a', 'b', 'c', 'd'}))
25.0
>>> cost.is_measured('unit')
True
```

An unknown tier is priced, not free — otherwise a cost-ordered scheduler
would run it first, precisely because nobody has ever timed it:

```pycon
>>> cost.estimate('nobody-timed-this', frozenset({'a'}))
60.0
```

The base check is read from its own regime rather than extrapolated:

```pycon
>>> cold = MeasuredCost()
>>> cold.observe('unit', frozenset(), 51.2)                  # base, cold
>>> for n in range(1, 10):
...     cold.observe('unit', frozenset(range(n)), 30.0 + n / 10)
>>> round(cold.estimate('unit', frozenset()), 1)             # its own regime
51.2
>>> round(cold.estimate('unit', frozenset(range(9))), 1)     # the body's
30.9
```

#### central(tier, size)

Seconds for a set of `size` at `tier`, before per-change extras.

The one place the model lives, so [`estimate()`](#mergeset.MeasuredCost.estimate) and
[`pessimistic()`](#mergeset.MeasuredCost.pessimistic) cannot drift apart.

Never below the fastest run ever observed for the tier. An evaluation
that has never taken less than 27 s will not take 0 s, and a floor of
zero is not merely inaccurate: it makes a budget check divide by nothing
and conclude the tier is unlimited.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### estimate(tier, subset)

Central estimate of what evaluating `subset` at `tier` will cost.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

```pycon
>>> cost = MeasuredCost(declared={'unit': 10.0}, per_change={'x': -50.0})
>>> cost.estimate('unit', frozenset({'x'}))
0.0
```

#### forget(tier)

Drop this tier’s observations, so a caller can re-ingest a log.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### is_measured(tier)

True iff this tier’s estimate comes from observations.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### observe(tier, subset, seconds)

Record one real timing, as a total or a per-stage breakdown.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### pessimistic(tier, subset)

Upper estimate: the central one plus the worst residual ever seen.

With no observations there is no residual to add and this is the central
estimate — the honest position, not an optimistic one: the declared or
unmeasured number is already the only thing known.

Note what this is *not* doing. The cold base check is priced by its own
regime (see [`central()`](#mergeset.MeasuredCost.central)), so it contributes no residual here. What
this carries is the spread *within* a regime, which is the variance no
candidate set predicts. The expensive regime is reserved explicitly by
the scheduler instead of being smuggled in as a hedge.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

```pycon
>>> cost = MeasuredCost()
>>> cost.observe('unit', frozenset({'a'}), 45.0)
>>> cost.observe('unit', frozenset({'a'}), 80.0)   # the lockfile moved
>>> round(cost.estimate('unit', frozenset({'a'})), 1)
62.5
>>> round(cost.pessimistic('unit', frozenset({'a'})), 1)
80.0
```

#### runs(tier)

How many timings this tier’s estimate rests on.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### summary()

Per-tier view of the model, for a report to print.

Says what the number is *and where it came from*, because an estimate
with no provenance is indistinguishable from a magic constant. This is
the published view of the evidence; the observation list itself is
private, so its shape can change without breaking callers.

* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### *class* mergeset.MemoryLines(iterable=(),)

Bases: [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

In-memory stand-in for [`JsonlLines`](#mergeset.JsonlLines) (tests, dry runs).

#### append(jdict)

Append object to the end of the list.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* mergeset.MergeOutcome(ok, reason='conflict', conflicting_files=(), assisted=False, assist_diff=None, order=(), detail='', resolved_commit=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of merging a change set onto its base.

`reason` is load-bearing. “These changes conflict with each other” and “we
could not run the experiment” are completely different facts, and conflating
them is how a run reports *0 of 15 mergeable, complete* with total
confidence when the real problem was a bad worktree path. Only
`reason == 'conflict'` may ever enter the conflict set; an `'error'`
aborts, because a set that was never tested has told us nothing.

#### reason *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'conflict'*

`'conflict'` (a real textual conflict) or `'error'` (the merge could
not be attempted: bad path, missing ref, unusable worktree).

#### resolved_commit *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

base plus every head,
conflicts resolved. A deeper tier checks this commit out instead of
asking the resolver again (i2mint/mergeset#30). Not in [`to_jdict()`](#mergeset.MergeOutcome.to_jdict):
[`Evaluation.to_jdict()`](#mergeset.Evaluation.to_jdict) stores it beside `merge`, because releases
before #30 build `MergeOutcome(**merge)` and would refuse the log.

* **Type:**
  The merge commit an assisted resolution produced

#### to_jdict()

JSON-able view (without [`resolved_commit`](#mergeset.MergeOutcome.resolved_commit); see there).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *exception* mergeset.MergesetError

Bases: [`Exception`](https://docs.python.org/3/builtins/exceptions.html#Exception)

Base class for errors this package raises deliberately.

### *class* mergeset.StageRun(name, duration=0.0, returncode=None, skipped=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one stage of a staged validation did, and what it cost.

A stage skipped because its fingerprint matched (an install whose lockfile
did not change) is recorded too, with `skipped=True` and no time: that
skip is often the largest term in what an evaluation costs, and a log that
cannot show it cannot confirm it (i2mint/mergeset#17).

```pycon
>>> StageRun.from_jdict(StageRun('setup', 33.0, 0).to_jdict())
StageRun(name='setup', duration=33.0, returncode=0, skipped=False)
```

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.StageRun.to_jdict).

* **Return type:**
  [`StageRun`](mergeset.base.html.md#mergeset.base.StageRun)

#### to_jdict()

JSON-able view.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* mergeset.StoreLines(store, key)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Lines backed by one key of a `MutableMapping` — the non-file backend.

[`JsonlLines`](#mergeset.JsonlLines) is the right thing over a filesystem: `open(..., 'a')`
is a true append. An object store has no append, so this reads, concatenates
and writes back. That is honest about the cost rather than pretending, and it
is what lets the evaluation log — the source of truth — reach S3 through the
same seam as everything else.

A missing key reads as empty rather than raising, so a first run works.

```pycon
>>> backing = {}
>>> lines = StoreLines(backing, 'run.jsonl')
>>> list(lines)
[]
>>> lines.append({'a': 1}); lines.append({'a': 2})
>>> [d['a'] for d in lines]
[1, 2]
>>> backing['run.jsonl']
'{"a": 1}\n{"a": 2}\n'
```

#### append(jdict)

Append one record by rewriting the value (no append primitive here).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* mergeset.Tier(name, validate, cost=None, available=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One rung of validation, from cheapest to dearest.

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What this tier is (`unit`, `integration`, `e2e`). It names
    the tier’s own evaluation log and appears in every claim the report
    makes, because “passed the unit tier” and “passed everything” are
    different facts.
  * **validate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]) – `worktree -> ValidationOutcome` — the same contract as every
    validator in [`mergeset.validation`](mergeset.validation.html.md#module-mergeset.validation), so
    [`staged_validation()`](mergeset.validation.html.md#mergeset.validation.staged_validation) and friends drop
    straight in. A tier is *one* validator; the stages *within* it are
    that validator’s own business.
  * **cost** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Declared seconds per run, used until the tier has been timed.
    Worth setting for a tier nobody has run yet: it is what stops a
    cost-ordered scheduler treating an unmeasured tier as cheap.
  * **available** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]) – `() -> bool` — is the infrastructure this tier needs up?
    The honest reason a tier gets skipped is usually not budget but
    absence: no daemon, no display, no credentials. `None` means
    always available, which is the truth for a unit-test tier.

```pycon
>>> from mergeset.validation import merge_only_validation
>>> tier = Tier('merge', merge_only_validation(), cost=0.5)
>>> tier.name, tier.is_available()
('merge', True)
>>> Tier('e2e', merge_only_validation(), available=lambda: False).is_available()
False
```

#### is_available()

Whether this tier can run right now.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### *class* mergeset.TieredAnalysis(tiers, analysis, logs, cost_model, depth_reached=None, skipped=<factory>, spent=<factory>, runs=<factory>, answer=None, must_include=frozenset({}), best_including=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of a tiered run.

`analysis` is an ordinary [`Analysis`](mergeset.analysis.html.md#mergeset.analysis.Analysis) whose
`maximal_sets`, `unverified_sets` and `notes` have been updated to the
depth validation actually reached — so every existing report renders it
unchanged and says the right thing about tiers.

#### best_including *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

Heaviest validated set containing every change in `must_include`.
`None` when they cannot all be kept together. A second, differently
constrained answer – never a replacement for the first.

#### cost_lines()

One line per tier: what its log records, and how the tier is priced.

Runs and seconds are read from the tier’s log, so they include earlier
invocations against the same commits, and the line says so. The price
says where it came from – `measured` from the log, `declared` by
the caller, or neither, in which case the model’s default is shown –
because an estimate with no provenance reads as a fact.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### depth_reached *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

How deep validation actually got, as a tier name.

#### *property* maximal_sets *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

maximal sets at the depth reached.

* **Type:**
  The answer

#### must_include *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)* *= frozenset({})*

Changes the caller required in the answer, if any.

#### runs *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [int](https://docs.python.org/3/builtins/functions.html#int)]*

Evaluations actually performed, per tier.

#### skipped *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

`tier -> why it did not run`. Empty is the normal case.

#### spent *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

Seconds spent per tier, measured from that tier’s log.

#### verified_tier(subset)

The deepest tier that recorded an exact PASS for `subset`.

Inference across the monotone closure deliberately does not count. A
passing *superset* is what makes a subset good by inference, and if such
a superset existed it would be the answer instead — so for the purpose
of “was this claim actually run”, only an exact recorded PASS counts.
D25’s rule, applied per tier.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* mergeset.ValidationOutcome(ok, failing_tests=(), failing_files=(), duration=0.0, stdout_tail='', returncode=None, stages=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of validating a merged tree.

#### *classmethod* from_jdict(d)

Inverse of [`to_jdict()`](#mergeset.ValidationOutcome.to_jdict); rows without `stages` read as none.

Keys it does not know are ignored, so a log written by a later version
still loads here instead of failing on its first new field.

* **Return type:**
  [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)

#### *property* stage_seconds *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

`{stage name: seconds}` for the stages that ran (skips excluded).

The shape [`mergeset.cost.Seconds`](mergeset.cost.html.md#mergeset.cost.Seconds) accepts as a breakdown. Two
stages sharing a name are summed, never overwritten.

```pycon
>>> ValidationOutcome(True, stages=[StageRun('setup', skipped=True),
...                                 StageRun('test', 6.0, 0)]).stage_seconds
{'test': 6.0}
```

#### stages *: [Sequence](https://docs.python.org/3/library/typing.html#typing.Sequence)[[StageRun](mergeset.base.html.md#mergeset.base.StageRun)]* *= ()*

Per-stage breakdown, in run order, for a staged validator; empty for a
single-command one and on rows written before stages were recorded.

#### to_jdict()

JSON-able view.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* mergeset.ValidationStage(name, command, fingerprint=None, timeout=None, required=True)

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

### *class* mergeset.Verdict(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Outcome of evaluating a change set.

### mergeset.act_validation(, job=None, timeout=None, env=None)

A validator that runs the repository’s GitHub Actions locally with `act`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.analyze(repo, changes, , base=None, validate=None, resolver=None, log=None, log_path=None, trust_unpinned=None, artifacts=None, weight=None, pairwise_preoracle=True, decompose=True, component_local=None, use_ci_status=True, check_base=True, max_evaluations=None, max_seconds=None, max_sets=None, worktree_root=None, reuse_worktree=None, on_event=None)

Find the maximal sets of `changes` that merge and validate on `base`.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to the git repository.
  * **changes** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]) – Candidate changes (see [`mergeset.sources`](mergeset.sources.html.md#module-mergeset.sources)).
  * **base** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – What to merge onto. Default: the merge base of every change’s own
    base, which is the only choice that is fair to all of them.
  * **validate** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]]) – `worktree -> ValidationOutcome`; default is a fail-fast
    pytest run. Pass `merge_only_validation()` for a free first pass.
  * **resolver** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]], [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – Optional AI-assisted conflict resolver (results are flagged).
  * **artifacts** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)]]) – The artifact stores, as a `{kind: MutableMapping}` mall (see
    [`mergeset.storage.artifact_mall()`](mergeset.storage.html.md#mergeset.storage.artifact_mall)). This is the storage seam:
    pass a mall over S3 and the evaluation log goes to S3 with no other
    change. Default: local files under `~/.local/share/mergeset/`.
  * **log_path** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The evaluation log — the single source of truth. Defaults
    to `<artifact root>/evaluations/<repo-slug>.jsonl` (see
    [`mergeset.storage`](mergeset.storage.html.md#module-mergeset.storage)), *outside* the analysed repository. Reusing
    an existing one makes a re-run nearly free. Only rows evaluated
    against the same base and heads, by the same validator, are reused
    (see ADR 0028 and [`mergeset.validation.fingerprint_of()`](mergeset.validation.html.md#mergeset.validation.fingerprint_of)).
  * **trust_unpinned** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Reuse log rows written before rows recorded their
    commits or their validator (an old log). Default: the log’s own
    setting, which is off. Only when neither the heads nor the
    validator have changed since those rows were written.
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Change`](mergeset.base.html.md#mergeset.base.Change)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `Change -> cost of dropping it`; default is size-based.
  * **pairwise_preoracle** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Use `git merge-tree` to find textual conflicts for
    free before spending any evaluation.
  * **decompose** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Use file-overlap components to find conflicts cheaply. The
    components are always searched first, because a conflict found
    inside a small component is a conflict found for a fraction of the
    price; whether their answers are then *trusted* to combine is
    `component_local`.
  * **component_local** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Assert that the validator cannot see across
    components — i.e. that two changes touching disjoint files can never
    fail together. True for a merge-only or per-file validator; \*\*false
    for any whole-repo test run\*\*, which can fail on generated
    artifacts, barrel exports, snapshots, type checks or project-wide
    lint that no changed-file overlap predicts. When false (the
    default), the combined result is verified by a global search seeded
    with every conflict the components found. `None` (the default)
    asks the validator: one may set `validate.component_local = True`
    to declare it, as [`merge_only_validation()`](mergeset.validation.html.md#mergeset.validation.merge_only_validation)
    does.
  * **check_base** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Evaluate the base commit on its own before anything else, so
    a broken base or a misconfigured validator is a refusal rather than
    15 confident failures.
  * **use_ci_status** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Treat a change whose own CI is red as a size-1 conflict.
  * **max_evaluations** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budgets; partial results are
    always returned.
  * **max_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Budgets; partial results are
    always returned.
  * **max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budgets; partial results are
    always returned.
  * **reuse_worktree** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Reuse one worktree for every evaluation instead of a
    fresh one, so an expensive setup step (`npm install`, a build
    cache) is paid once rather than per evaluation. Pair it with
    [`mergeset.validation.staged_validation()`](mergeset.validation.html.md#mergeset.validation.staged_validation).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – `(event, payload)` progress callback.
* **Return type:**
  [`Analysis`](mergeset.analysis.html.md#mergeset.analysis.Analysis)
* **Returns:**
  An [`Analysis`](#mergeset.Analysis).

### mergeset.analyze_tiered(repo, changes, , tiers, cost_model=None, confirm_budget_seconds=None, confirm_max_runs=None, confirm_max_sets=None, must_include=(), on_event=None, \*\*analyze_kwargs)

Screen with the cheap tier, confirm the frontier with the expensive ones.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – As [`mergeset.analyze()`](#mergeset.analyze).
  * **changes** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]) – As [`mergeset.analyze()`](#mergeset.analyze).
  * **tiers** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Tier`](mergeset.tiers.html.md#mergeset.tiers.Tier)]) – Ordered cheapest-first. The first is the **screen** and pays for
    the whole search interior; each later one confirms what its
    predecessor left standing. One tier reproduces today’s behaviour
    exactly.
  * **cost_model** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`CostModel`](mergeset.cost.html.md#mergeset.cost.CostModel)]) – The price list — a seam. Default:
    [`MeasuredCost`](mergeset.cost.html.md#mergeset.cost.MeasuredCost) seeded from each tier’s
    declared `cost`, then fitted to the durations the tier’s own
    evaluation log records. Measurements from one run price the next.
  * **confirm_budget_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Wall-clock a deep tier may spend. Admission uses
    the model’s *pessimistic* estimate, because overrunning a budget is
    worse than deferring one evaluation.
  * **confirm_max_runs** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Hard cap on evaluations per deep tier. Takes
    precedence over the budget when both are given.
  * **confirm_max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Stop a deep tier after this many confirmed maximal
    sets. `1` is “just tell me the single best plan, cheaply”.
  * **must_include** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Changes that must be in the answer. Answers a *different*
    question alongside the main one — “the best plan that keeps this” —
    and the two can be far apart when the required change conflicts with
    members of the unconstrained best plan. Reported as
    `TieredAnalysis.best_including`; see [`best_set_including()`](#mergeset.best_set_including).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – `(event, payload)`. Adds `tier`, `tier_skipped` and
    `anytime` on top of the events [`mergeset.analyze()`](#mergeset.analyze) emits, so
    a caller can display the best-so-far after every deep run.
  * **\*\*analyze_kwargs** – Everything else goes to [`mergeset.analyze()`](#mergeset.analyze)
    unchanged (`base`, `decompose`, `max_evaluations`, …). Not
    `validate` and not `log`: the tiers own both.
* **Return type:**
  [`TieredAnalysis`](mergeset.tiers.html.md#mergeset.tiers.TieredAnalysis)
* **Returns:**
  A [`TieredAnalysis`](#mergeset.TieredAnalysis).

### mergeset.ancestors(change, parents)

Every change `change` is stacked on, transitively.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(ancestors('c', {'c': 'b', 'b': 'a'}))
('a', 'b')
```

### mergeset.anytime_answer(change_ids, conflicts, , weight, verified, tiers, cost_model=None, remaining_tiers=(), depends_on=None, spent=None, pending_limit=5, bound_search_limit=64)

The best validated set so far, plus a sound bound on what is being missed.

* **Parameters:**
  * **change_ids** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The universe.
  * **conflicts** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Every refuted set, from any tier or pre-oracle.
  * **weight** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – `change id -> weight`; a set’s weight is the sum of its own.
  * **verified** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `(set, deepest tier that ran on it)` pairs.
  * **tiers** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Tier`](mergeset.tiers.html.md#mergeset.tiers.Tier)]) – The tier chain, which is what “full depth” means.
  * **cost_model** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`CostModel`](mergeset.cost.html.md#mergeset.cost.CostModel)]) – Used to price `pending`.
  * **remaining_tiers** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Used to price `pending`.
  * **depends_on** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `child -> parent` for stacked changes. Without it the
    bound names sets that could never land — a child without its parent
    — so `optimal` never becomes true however much is validated, and
    `pending` prices candidates nobody can run.
  * **bound_search_limit** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many minimal hitting sets to consider when
    tightening the bound under stack closure. Closure can only shrink a
    complement, so it breaks the weight ordering the enumeration relies
    on; past this many, the loose-but-sound unclosed bound is used.
  * **spent** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Seconds per tier, carried through for reporting.
  * **pending_limit** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many unconfirmed candidates to price.
* **Return type:**
  [`AnytimeAnswer`](mergeset.tiers.html.md#mergeset.tiers.AnytimeAnswer)

```pycon
>>> tiers = [Tier('unit', lambda w: None), Tier('e2e', lambda w: None)]
>>> answer = anytime_answer(
...     ['a', 'b', 'c'], [frozenset({'a', 'b'})], weight=lambda c: 1.0,
...     verified=[(frozenset({'a', 'c'}), 'e2e')], tiers=tiers)
>>> answer.best_weight, answer.bound, answer.optimal
(2.0, 2.0, True)
```

Same conflicts, but the deep tier never ran. The bound is unchanged and the
answer is explicitly *not* optimal, because a tier that did not run is not a
tier that passed:

```pycon
>>> partial = anytime_answer(
...     ['a', 'b', 'c'], [frozenset({'a', 'b'})], weight=lambda c: 1.0,
...     verified=[(frozenset({'a', 'c'}), 'unit')], tiers=tiers)
>>> partial.optimal, partial.full_depth, partial.best_tier
(False, False, 'unit')
```

### mergeset.app_data_rootdir(, app_name='mergeset', envvar='MERGESET_DATA_DIR')

The artifact root for `app_name`, honouring `$MERGESET_DATA_DIR`.

It is a *root*, not a leaf: artifacts always go in a per-kind subfolder of
it (see [`artifact_store()`](#mergeset.artifact_store)), so a new kind never needs a migration.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> import os, tempfile
>>> d = tempfile.mkdtemp()
>>> os.environ['MERGESET_DATA_DIR'] = d
>>> app_data_rootdir() == d
True
>>> del os.environ['MERGESET_DATA_DIR']
>>> app_data_rootdir().endswith('mergeset')
True
```

### mergeset.artifact_mall(, rootdir=None, store_factory=None, kinds=('reports', 'evaluations', 'logs', 'fixtures'), app_name='mergeset', binary=False)

All the artifact stores, keyed by kind — a *mall*, in `dol` terms.

Stores are built lazily, so asking for the mall never creates a directory
for a kind you do not use.

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)]

```pycon
>>> import tempfile
>>> mall = artifact_mall(rootdir=tempfile.mkdtemp())
>>> mall['evaluations']['a.jsonl'] = '{}\n'
>>> list(mall['evaluations'])
['a.jsonl']
```

### mergeset.artifact_path(kind, key='', , rootdir=None, app_name='mergeset')

Filesystem path for `kind`/`key` under the *local* artifact root.

The escape hatch for the things that genuinely need a path rather than a
store — the append-only evaluation log, and a subprocess told where to write
its own output. Everything else should go through [`artifact_store()`](#mergeset.artifact_store),
because a path is exactly the coupling the store exists to remove.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> import tempfile
>>> root = tempfile.mkdtemp()
>>> artifact_path('evaluations', 'x.jsonl', rootdir=root) == \
...     __import__('os').path.join(root, 'evaluations', 'x.jsonl')
True
```

### mergeset.artifact_store(kind, , rootdir=None, store_factory=None, app_name='mergeset', binary=False)

A store for one kind of artifact — `str` values, or `bytes`.

* **Parameters:**
  * **kind** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – One of `ARTIFACT_KINDS` (any name works; the tuple is the
    set mergeset itself uses).
  * **rootdir** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Artifact root. Defaults to [`app_data_rootdir()`](#mergeset.app_data_rootdir).
  * **store_factory** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)]]) – The backend seam —
    `(kind, rootdir, *, binary) -> MutableMapping`, defaulting to
    `dol` files under `<rootdir>/<kind>/`. Swap it for S3, a
    database, or a dict without touching a single caller.
  * **binary** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Values are `bytes` rather than `str`. A run’s PDF and its
    Markdown share one directory and differ only in this flag.
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

```pycon
>>> import tempfile
>>> store = artifact_store('logs', rootdir=tempfile.mkdtemp())
>>> store['run-1.log'] = 'all green'
>>> store['run-1.log']
'all green'
```

### mergeset.best_set_including(change_ids, evaluate, \*, must_include, conflicts=(), weight=None, depends_on=None, max_evaluations=None, shrink=<function quickxplain>)

The heaviest validated set that **contains** every change in `must_include`.

This is a different question from “the heaviest validated set”, and on real
data the two answers can be far apart. A change that must land — because it
is the one the expensive tier exists for, or because someone has decided it
ships — may conflict with several members of the unconstrained best plan; the
best plan that keeps it is then not a superset of that plan, not a subset,
and not reachable by adding anything to it. It is the complement of a minimal
hitting set that *avoids* the required changes, which is what this
enumerates.

* **Parameters:**
  * **change_ids** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The universe.
  * **evaluate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]) – The (chained, log-cached) oracle.
  * **must_include** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Changes the answer must contain. With stacked changes the
    set is closed downward first, since keeping a change means keeping
    what it is built on.
  * **conflicts** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflicts already known — the point of the exercise is to
    reuse everything the unconstrained search learned.
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `id -> weight`; candidates are proposed heaviest-first.
  * **depends_on** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `child -> parent` for stacked changes.
  * **max_evaluations** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budget, in real (uncached) evaluations.
  * **shrink** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflict-minimization strategy.
* **Return type:**
  [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`int`](https://docs.python.org/3/builtins/functions.html#int)]
* **Returns:**
  `(best set or None, the conflicts now known, evaluations spent)`.
  `None` means the required changes cannot all be kept: every way of
  resolving the known conflicts drops one of them.

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> def oracle(subset):                      # 'h' conflicts with 'a' and 'b'
...     bad = {'h', 'a'} <= subset or {'h', 'b'} <= subset
...     return Evaluation(subset, Verdict.FAIL if bad else Verdict.PASS)
>>> best, _, _ = best_set_including('abch', oracle, must_include=['h'])
>>> set_key(best)
('c', 'h')
```

Unconstrained, the answer would have been the three changes that exclude
`h` — bigger, and not an answer to the question that was asked.

### mergeset.branch_changes(repo, branches, , base='HEAD', prefix='')

Changes from local or remote branches.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]

```pycon
>>> list(branch_changes('.', []))
[]
```

### mergeset.bundled_skills(skills_root=None)

Yield the directory of every bundled skill (each holding a `SKILL.md`).

`skills_root` is resolved, so a relative one still yields links that work
from anywhere.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

```pycon
>>> [p.name for p in bundled_skills()]
['mergeset']
```

### mergeset.callable_validation(func)

Adapt a plain user callable into a validator.

The callable may return a [`ValidationOutcome`](#mergeset.ValidationOutcome) (used as-is) or
anything truthy/falsy (interpreted as pass/fail).

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.chained_evaluate(evaluators)

Compose per-tier evaluators into one, short-circuiting on the first failure.

This is the lever. A set the cheap tier refutes never reaches the expensive
one, so the search’s interior — every hitting-set probe, every QuickXplain
step — is paid at cheap-tier prices, and the expensive tier is spent only on
sets that survived.

```pycon
>>> def cheap(s):
...     return Evaluation(s, Verdict.FAIL if 'bad' in s else Verdict.PASS)
>>> deep_calls = []
>>> def deep(s):
...     deep_calls.append(set_key(s))
...     return Evaluation(s, Verdict.PASS)
>>> evaluate = chained_evaluate([cheap, deep])
>>> evaluate(frozenset({'bad', 'x'})).verdict.value
'fail'
>>> deep_calls
[]
>>> evaluate(frozenset({'x'})).verdict.value
'pass'
>>> deep_calls
[('x',)]
```

### mergeset.change_set(ids)

Normalize any iterable of change ids into a `frozenset`.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> change_set(['b', 'a', 'b']) == frozenset({'a', 'b'})
True
```

### mergeset.changed_files(repo, base, head)

Files a change touches, as `git diff --name-only base...head`.

The three-dot form is deliberate: it compares against the merge base, so a
change is measured by what *it* did, not by what happened on base meanwhile.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.claude_code_resolver(, timeout=300.0, command='claude')

Resolve conflicts with a Claude Code subagent, under a strict policy.

The policy is in the prompt and is deliberately narrow: mechanical conflicts
only (import blocks, changelog entries, adjacent independent edits, lockfile
regeneration), and an explicit refusal whenever the resolution requires
guessing intent. Anything it does resolve is flagged and its diff kept.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]], [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### mergeset.close_down(subset, parents)

Add every ancestor, so the set becomes a valid thing to ask for.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(close_down({'c'}, {'c': 'b', 'b': 'a'}))
('a', 'b', 'c')
```

### mergeset.close_up(subset, parents)

Add every descendant — what dropping these changes actually costs.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(close_up({'a'}, {'c': 'b', 'b': 'a'}))
('a', 'b', 'c')
```

### mergeset.combine_components(per_component)

Cartesian-combine per-component maximal sets into global ones.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

```pycon
>>> [set_key(s) for s in combine_components([[frozenset('a')], [frozenset('c')]])]
[('a', 'c')]
```

### mergeset.command_validation(command, , timeout=None, env=None)

A validator that runs an arbitrary shell command in the merged worktree.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.commit_changes(repo, commits, , base='HEAD')

Changes from an explicit list of commit-ishes, one change per commit.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]

### mergeset.cone_weights(weights, parents)

Re-weight each change by the cost of dropping its whole descendant cone.

Dropping a stack’s root drops the stack. The hitting set has to know that,
or it will pick the “cheapest” change and take eight thousand lines with it.

* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

```pycon
>>> cone_weights({'a': 1.0, 'b': 2.0}, {'b': 'a'})
{'a': 3.0, 'b': 2.0}
```

### mergeset.cost_from_log(log, , tier, declared=None, per_change=None, unmeasured_seconds=60.0)

Seed a cost model from an existing evaluation log — the real default.

Every row of the log already carries `subset` and `duration`, so the
price of the tier that produced that log is not a thing anyone needs to
declare: it has been measured, repeatedly, and thrown away. This reads it
back.

`tier` names which tier those rows belong to, because the log itself does
not say — one log holds one tier’s rows by construction
(see [`mergeset.tiers`](mergeset.tiers.html.md#module-mergeset.tiers)).

* **Return type:**
  [`MeasuredCost`](mergeset.cost.html.md#mergeset.cost.MeasuredCost)

```pycon
>>> from mergeset.base import Evaluation, Verdict
>>> rows = [Evaluation(frozenset({'a'}), Verdict.PASS, duration=40.0),
...         Evaluation(frozenset({'a', 'b', 'c'}), Verdict.FAIL, duration=60.0)]
>>> cost = cost_from_log(rows, tier='unit')
>>> cost.estimate('unit', frozenset({'a', 'b'}))
50.0
```

### mergeset.count_closed_subsets(parents, changes)

How many downward-closed subsets exist — the size of the real search space.

Worth reporting: on a 15-change forest of four stacks this is 576 rather
than 32768, which is the difference between “enumerate carefully” and
“hopeless”.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

```pycon
>>> count_closed_subsets({'b': 'a'}, ['a', 'b'])
3
```

### mergeset.create_integration_branch(repo, name, base, heads, , force=False)

Create a local branch holding `base` + all heads, for manual testing.

Only ever creates *new* local branches. Never touches an existing branch
unless `force` is passed explicitly, and never pushes anything.

* **Return type:**
  [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  `(created, message)`.

### mergeset.descendants(change, parents)

Every change stacked on `change`, transitively — its *cone*.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(descendants('a', {'c': 'b', 'b': 'a', 'd': 'a'}))
('b', 'c', 'd')
```

### mergeset.detect_stacks(changes)

Map change id -> the change id it is stacked on, for PR stacks.

A PR whose base ref is another candidate’s head ref is *stacked*: only
prefixes of the chain make sense as a merge set, because the child contains
the parent. Recorded so the report can say so and the solver can be told.

* **Return type:**
  [`Dict`](https://docs.python.org/3/library/typing.html#typing.Dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> a = Change(id='pr1', head='origin/a', base='origin/main', source='pr',
...            meta={'head_ref': 'a', 'base_ref': 'main'})
>>> b = Change(id='pr2', head='origin/b', base='origin/a', source='pr',
...            meta={'head_ref': 'b', 'base_ref': 'a'})
>>> detect_stacks([a, b])
{'pr2': 'pr1'}
```

### mergeset.evaluation_lines(repo, , store=None, rootdir=None, app_name='mergeset')

The append-only lines object backing this repo’s evaluation log.

With no `store`, the local filesystem backend is used directly, because
`open(path, 'a')` is a *true* append and re-writing a growing log on every
evaluation is not. With a `store` (S3, a database, a dict), the log goes
through it like every other artifact — the source of truth is not allowed to
be the one thing that cannot leave the filesystem.

```pycon
>>> import tempfile
>>> lines = evaluation_lines('/x/proj/widget', rootdir=tempfile.mkdtemp())
>>> lines.append({'a': 1}); [d['a'] for d in lines]
[1]
```

```pycon
>>> backing = {}
>>> lines = evaluation_lines('/x/proj/widget', store=backing)
>>> lines.append({'a': 1}); list(backing)[0].endswith('.jsonl')
True
```

### mergeset.evaluation_log_path(repo, , rootdir=None, app_name='mergeset')

Default evaluation-log path for `repo` — in the artifact store.

Deliberately **not** `<repo>/.mergeset/evaluations.jsonl`: that writes a
file capturing one repository’s internals into that same repository, which
is how derived data ends up committed.

`repo` is resolved to an absolute path first, so `'.'` names the current
directory rather than collapsing every project into one `repo.jsonl`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> import tempfile, os
>>> p = evaluation_log_path('/x/proj/widget', rootdir=tempfile.mkdtemp())
>>> os.path.basename(p).startswith('proj-widget-')
True
>>> os.path.basename(p).endswith('.jsonl')
True
```

### mergeset.fetch_pull_requests(repo_spec, , author=None, state='open', limit=100, extra_args=())

Raw `gh pr list` records for `repo_spec` (`owner/name`).

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### mergeset.file_fingerprint(\*paths)

A fingerprint function over the contents of the given repo-relative files.

The canonical use is a lockfile: install dependencies again only when
`pnpm-lock.yaml` actually changed between two candidate merges.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.find_maximal_good_sets(changes, evaluate, \*, known_conflicts=(), depends_on=None, weight=None, max_evaluations=None, max_seconds=None, max_sets=None, shrink=<function quickxplain>, suspects=None, on_event=None)

Enumerate maximal good subsets of `changes`, cheapest-dropped first.

* **Parameters:**
  * **changes** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The change ids in play.
  * **evaluate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]) – The (cached, log-backed) oracle.
  * **known_conflicts** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflicts already known for free — e.g. textual
    `git merge-tree` conflicts and singletons whose own CI is red.
    These cost zero evaluations and prune enormously.
  * **depends_on** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `child -> parent` for stacked changes. When given, only
    downward-closed sets are ever proposed (a change is never evaluated
    without the changes it is built on) and dropping a change implicitly
    drops everything stacked on it. See [`mergeset.stacks`](mergeset.stacks.html.md#module-mergeset.stacks).
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `id -> cost of dropping it`. Higher means “keep me”.
  * **max_evaluations** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budgets. Whichever trips first
    stops the search; partial results are always returned.
  * **max_seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Budgets. Whichever trips first
    stops the search; partial results are always returned.
  * **max_sets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Budgets. Whichever trips first
    stops the search; partial results are always returned.
  * **shrink** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – Conflict-minimization strategy ([`quickxplain()`](#mergeset.quickxplain) by default).
  * **suspects** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]]) – `(failed evaluation, the set) -> the changes it implicates`.
    Lets the search shrink within the implicated changes instead of
    halving the whole set. A wrong hint costs one wasted check and then
    falls back; see [`mergeset.attribution`](mergeset.attribution.html.md#module-mergeset.attribution).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – `(event_name, payload)` progress callback.
* **Return type:**
  [`SearchState`](mergeset.solve.html.md#mergeset.solve.SearchState)
* **Returns:**
  A `SearchState`. `exhausted` says whether the answer is
  complete or merely the best found within budget.

```pycon
>>> bad = [{'a', 'c'}]
>>> def ev(s):
...     ok = not any(p <= set(s) for p in bad)
...     return Evaluation(s, Verdict.PASS if ok else Verdict.FAIL)
>>> state = find_maximal_good_sets(['a', 'b', 'c'], ev)
>>> [set_key(s) for s in state.maximal_good_sets]
[('a', 'b'), ('b', 'c')]
>>> [set_key(c) for c in state.conflicts]
[('a', 'c')]
```

### mergeset.flake_tolerant(validate, , retries=1)

Re-run a failing validation `retries` times before believing it.

Monotonicity is a prior, not a law, and flaky tests are the usual way it
breaks. This is the cheap defense; the honest one is
`EvaluationLog.monotonicity_violations`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.git_oracle(repo, base, changes, , validate=None, resolver=None, resolution=None, depends_on=None, reuse_worktree=None, worktree_root=None, keep_worktrees=False, on_event=None)

Build the evaluator: merge the set onto `base`, then validate the tree.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to the git repository (worktrees are created off it).
  * **base** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The commit everything is merged onto.
  * **changes** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]) – The changes in play; only their ids are passed around later.
  * **validate** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]]) – `worktree -> ValidationOutcome`. Defaults to a fail-fast
    pytest run; see [`mergeset.validation`](mergeset.validation.html.md#module-mergeset.validation) for the alternatives.
  * **resolver** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]], [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – Optional AI-assisted conflict resolver. When given, a textual
    conflict is offered to it; a success is recorded with
    `merge.assisted = True`, the diff kept, and the resolved merge
    commit kept as `merge.resolved_commit`.
  * **resolution** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`MergeOutcome`](mergeset.base.html.md#mergeset.base.MergeOutcome)]]]) – `subset -> MergeOutcome` of an earlier assisted
    resolution of that set, or `None` – the alternative to
    `resolver` for a deeper tier (i2mint/mergeset#30). A conflicting
    set is then not resolved again: the recorded commit is checked out,
    once it is shown to hold the base and every head, so every tier
    validates the very tree the first one did and the resolver is paid
    once. A conflict with no usable recorded resolution is an
    `ERROR`, never a guess.
  * **depends_on** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – `child -> parent` for stacked changes. Only the *tips* of
    a set are merged, because merging a tip already brings its
    ancestors; merging them explicitly is wasted work and perturbs the
    merge order for no reason.
  * **reuse_worktree** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An existing worktree to check every candidate merge out
    into, instead of a fresh one per evaluation. This is what makes an
    expensive per-tree setup (dependency install, build cache)
    amortizable across the whole run.
  * **worktree_root** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Where throwaway worktrees go. Default: a temp dir.
  * **keep_worktrees** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Keep them for inspection (they add up fast).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – `(event, payload)` progress callback.
* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]
* **Returns:**
  `evaluate(subset) -> Evaluation`. Wrap it in
  `EvaluationLog.caching` before handing it to the solver.

### mergeset.html_report(analysis, , title='mergeset')

Render the analysis as one self-contained HTML file.

No build step, no CDN, no network: a single file that can be opened from
disk or attached to an issue. It draws the conflict graph (nodes = changes,
edges = conflicts, textual vs validation distinguished), the maximal sets,
and the evaluation timeline.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.independent_components(changes, files_of)

Split changes into groups that cannot possibly interact via files.

Two changes touching disjoint file sets cannot conflict textually, and (as a
working assumption worth stating out loud) rarely conflict semantically.
Connected components of the file-overlap graph are therefore independent
subproblems: solve each separately and combine the answers freely, which
turns one `2**n` search into several much smaller ones.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

```pycon
>>> files = {'a': ['x.py'], 'b': ['x.py'], 'c': ['y.py']}
>>> [set_key(g) for g in independent_components(files, files.get)]
[('a', 'b'), ('c',)]
```

### mergeset.install_skills(target='~/.claude/skills', , skills_root=None, link=True, overwrite=False)

Put the bundled skills where an agent host will find them.

Returns the destination path of every skill installed. A destination that
already holds a skill is left alone, so re-running is safe and an edited
skill is never silently replaced — and anything *else* sitting in the way
(a file, a stale broken link) raises rather than being reported as fine.

`overwrite=True` is the escape hatch, and it is not gentle: it deletes
whatever is at the destination, including a directory someone kept notes in.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> import tempfile
>>> dest = tempfile.mkdtemp()
>>> installed = install_skills(dest)
>>> [Path(p).name for p in installed]
['mergeset']
>>> Path(installed[0], 'SKILL.md').read_text().startswith('---')
True
>>> install_skills(dest)          # already there, nothing to do
[]
```

### mergeset.js_validation(, install='pnpm install --frozen-lockfile', build=None, test='pnpm run test', lint=None, lockfile='pnpm-lock.yaml', timeout=None)

A staged validator shaped like a JavaScript project.

Install is fingerprinted on the lockfile so it runs only when dependencies
actually changed; the build, when given, is a required prerequisite of the
tests rather than part of them.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.largest_closed_subset(subset, parents)

Drop members whose ancestors are missing — the set you can actually merge.

This is the *other* way to make a set valid, and it is the one the solver
needs: when the search decides to drop a parent, the descendants have to go
too, and no amount of wanting them back changes that.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(largest_closed_subset({'b', 'c'}, {'c': 'b', 'b': 'a'}))
()
>>> set_key(largest_closed_subset({'a', 'b', 'd'}, {'c': 'b', 'b': 'a'}))
('a', 'b', 'd')
```

### mergeset.local_branch_names(repo, , pattern=None, exclude=())

Local branch names, optionally filtered by a glob `pattern`.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.markdown_report(analysis, , title='mergeset report')

Render the analysis as Markdown.

Sections, in the order a reader actually wants them: what to merge, what
stops the rest, and only then the evidence.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.merge_only_validation()

A validator that accepts anything that merged cleanly.

Useful as a first pass: it costs nothing and still finds every textual
conflict, which on real branch sets is most of them.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.html.md#mergeset.base.ValidationOutcome)]

### mergeset.merge_order(subset, changes)

A deterministic merge order for a change set.

Order should not matter when merges are clean; when it does, the run is
recorded with the order that was used so the result stays reproducible.
Stacked changes are merged parent-first; otherwise smallest-first, which
surfaces the cheap conflicts early.

* **Return type:**
  [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> merge_order(frozenset({'b', 'a'}), {})
['a', 'b']
```

### mergeset.merge_sequence(repo, base, heads)

Merge every head onto `base`, one at a time, without any worktree.

The mechanic, which is the cheap heart of the whole tool:

```default
acc = base
for each head:
    tree = git merge-tree --write-tree acc head   # conflict -> non-zero
    acc  = git commit-tree tree -p acc -p head
```

`n` `merge-tree` calls of a few milliseconds each, no checkout, no
working tree, and — when it comes out clean — a real commit that a worktree
can be checked out from only if we actually intend to run tests on it.

Every merge is measured against the accumulated result rather than pairwise,
which is what keeps a stale branch from manufacturing false conflicts.

* **Return type:**
  [`SequenceMerge`](mergeset.gitops.html.md#mergeset.gitops.SequenceMerge)

### mergeset.merged_worktree(repo, base, heads, , root=None, keep=False, reuse=None)

Materialize `base` plus every head in a worktree, ready for validation.

The merge itself happens in the object database ([`merge_sequence()`](#mergeset.merge_sequence)), so
a conflicted set costs milliseconds and never touches the filesystem at all.
Only a *clean* set gets checked out — which is the only case where anything
wanted to run tests anyway.

Yields `(worktree_path, outcome)`. On a conflict the path is `None` and
the outcome names the change that failed (`outcome.order[-1]`) and the
conflicting files — that attribution is what lets the solver shrink straight
to the suspects instead of halving blindly.

* **Parameters:**
  **reuse** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An existing worktree to check the merge commit out into, instead
  of creating a fresh one. This is the seam that makes expensive
  per-tree setup (`npm install`, a virtualenv, a build cache)
  survive across evaluations; see
  [`mergeset.validation.staged_validation()`](mergeset.validation.html.md#mergeset.validation.staged_validation).
* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`MergeOutcome`](mergeset.base.html.md#mergeset.base.MergeOutcome)]]

### mergeset.minimal_hitting_sets(conflicts, , weight=None, limit=None)

Yield minimal hitting sets of `conflicts`, cheapest total weight first.

A hitting set touches every conflict; its complement is therefore a set with
no known conflict inside it. Enumerating hitting sets cheapest-first means
the solver proposes dropping the *least valuable* changes first.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]

```pycon
>>> hs = minimal_hitting_sets([frozenset({'a', 'b'}), frozenset({'b', 'c'})])
>>> [sorted(h) for h in itertools.islice(hs, 3)]
[['b'], ['a', 'c']]
```

### mergeset.pairwise_textual_conflicts(repo, base, heads)

Yield `(id_a, id_b, files)` for every pair that conflicts textually.

`heads` maps change id -> commit-ish. This is the pre-oracle that buys the
most: every pair it finds is a size-2 conflict known before any test runs.
Each pair is merged *onto base*, never against each other — see
[`textual_conflict()`](#mergeset.textual_conflict) for why that distinction is not cosmetic.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]

### mergeset.persistent_worktree(repo, base, path)

Create (once) a worktree meant to be reused across many evaluations.

Reusing one tree is what makes an expensive setup step amortizable: install
dependencies once, then check out each candidate merge into the same
directory. Returns `path`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.pr_changes(repo, pull_requests, , base=None, ref_of=None)

Turn `gh pr list` records into changes.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Local clone the refs live in.
  * **pull_requests** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Records as produced by [`fetch_pull_requests()`](#mergeset.fetch_pull_requests).
  * **base** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Override base for every change. Default: each PR’s own base ref,
    which is what makes stacked PRs visible rather than silently wrong.
  * **ref_of** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – How to name a PR’s head ref locally. Default `origin/<headRef>`.
* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]

### mergeset.pytest_validation(, args=('-x', '-q', '--tb=short', '-p', 'no:cacheprovider'), timeout=None, env=None, select_paths=None)

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

### mergeset.quickxplain(evaluate, candidates, , background=frozenset({}))

Shrink a known-bad set to one minimal conflict, in O(k log n) evaluations.

Junker’s QuickXplain: recursive halving that costs `O(k log(n/k))`
evaluations for a conflict of size `k` among `n` candidates, rather than
the `O(n)` of naive one-at-a-time removal.

* **Parameters:**
  * **evaluate** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.html.md#mergeset.base.Evaluation)]) – The (cached) oracle.
  * **candidates** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Members that may be part of the conflict.
  * **background** ([`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)) – Members always present and assumed not, on their own, bad.
* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)
* **Returns:**
  A minimal subset `C` of `candidates` with `background | C` bad.

```pycon
>>> bad_pairs = [{'a', 'c'}]
>>> def ev(s):
...     ok = not any(p <= set(s) for p in bad_pairs)
...     return Evaluation(s, Verdict.PASS if ok else Verdict.FAIL)
>>> sorted(quickxplain(ev, ['a', 'b', 'c', 'd']))
['a', 'c']
```

### mergeset.run_key(repo, , at=None)

A key naming one run of one repository: `<repo-slug>/<timestamp>`.

Reports are keyed by run, not by repository, so a second analysis of the
same repo does not overwrite the first. The 18-PR re-run of an earlier
analysis is exactly the case that made this necessary: the interesting thing
about it is the *diff* against the previous run, and there is no diff if the
previous run was clobbered.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> key = run_key('/x/proj/widget', at='2026-09-09T14-00-00Z')
>>> key.endswith('/2026-09-09T14-00-00Z')
True
>>> key.startswith('proj-widget-')
True
```

### mergeset.set_cost(cost_model, tiers, subset, , pessimistic=False)

What it costs to take `subset` all the way down `tiers`.

The tiers run in order and every one of them runs, so the price of a full
verdict is their sum — which is exactly what makes a cheap first tier worth
having: most sets never reach the second term.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

```pycon
>>> cost = MeasuredCost(declared={'unit': 45.0, 'e2e': 300.0})
>>> set_cost(cost, ['unit', 'e2e'], frozenset({'a'}))
345.0
```

### mergeset.set_key(ids)

A stable, hashable, JSON-friendly key for a change set.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)

```pycon
>>> set_key({'b', 'a'})
('a', 'b')
```

### mergeset.singleton_textual_conflicts(repo, base, heads)

Yield `(id, files)` for every change that will not even merge onto base.

The cheapest check there is, and on real PR sets it fires more than you would
expect: a PR opened against a base branch that has since moved on is green on
GitHub and still unmergeable onto the base you actually care about.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]

### mergeset.skills_dir()

The directory of skills bundled inside the installed package.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

```pycon
>>> skills_dir().name
'skills'
```

### mergeset.slash_separated_keys(store, , sep='/')

Make `/` the key separator whatever the platform’s is.

Keys are a store’s public namespace, so they must not change shape with the
operating system: a report written under `'run-a/REPORT.md'` has to read
back under that key on Windows too, and an S3 backend uses `/` regardless.
Without this the same key is two different keys on two machines — the
filesystem leaking through the abstraction the store exists to provide.

A no-op where the separator is already `/`.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

```pycon
>>> store = slash_separated_keys({}, sep='/')
>>> store['a/b'] = 1; dict(store)
{'a/b': 1}
```

On a backslash platform the *backing* store sees native separators while
callers keep using `/`:

```pycon
>>> backing = {}
>>> store = slash_separated_keys(backing, sep='\\')
>>> store['a/b'] = 1
>>> list(backing)
['a\\b']
>>> list(store), store['a/b']
(['a/b'], 1)
```

### mergeset.staged_validation(stages, , env=None)

Run an ordered list of [`ValidationStage`](#mergeset.ValidationStage) steps, reporting which one failed.

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

### mergeset.textual_conflict(repo, base, head_a, head_b)

Conflicting files if merging both heads onto `base` clashes textually.

\*\*This chains through `base` on purpose.\*\* Plain `git merge-tree A B`
merges using `merge-base(A, B)`, which is *not* `base` whenever the two
branches were cut at different times — and then it reports base’s own
commits as conflicts. On a real 15-PR set that mistake produced 13
“conflicting” pairs where only 2 were real (measured by TEST on
a real trial). So we merge A onto base first, in the object database, and ask
whether B then conflicts with *that*.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]
* **Returns:**
  `None` when the merge is clean, otherwise the list of conflicted paths
  (possibly empty if git reported a conflict it could not attribute).

### mergeset.tier_lines(repo, tier, , store=None)

The append-only lines object backing one tier’s evaluation log.

One log per tier, in the same artifact store as everything else, keyed by
repository *and* tier. Sharing one log between tiers would make a cheap
PASS answer an expensive question, which is the one thing this module
exists to prevent — so both halves of the key are slugified.

```pycon
>>> backing = {}
>>> lines = tier_lines('/x/proj/widget', 'e2e', store=backing)
>>> lines.append({'a': 1}); list(backing)[0].endswith('.e2e.jsonl')
True
```

### mergeset.tips(subset, parents)

The members of `subset` that nothing else in `subset` is stacked on.

Merging these brings the rest along for free.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

```pycon
>>> set_key(tips({'a', 'b', 'c'}, {'c': 'b', 'b': 'a'}))
('c',)
>>> set_key(tips({'a', 'b', 'd'}, {'b': 'a', 'd': 'a'}))
('b', 'd')
```

### Modules

| [`analysis`](mergeset.analysis.html.md#module-mergeset.analysis)       | The facade: one call that goes from a repository to a merge plan.                                             |
|------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`attribution`](mergeset.attribution.html.md#module-mergeset.attribution) | From a failure to the changes that probably caused it.                                                        |
| [`base`](mergeset.base.html.md#module-mergeset.base)               | Core data structures and vocabulary of `mergeset`.                                                            |
| [`cli`](mergeset.cli.html.md#module-mergeset.cli)                 | Command line surface.                                                                                         |
| [`cost`](mergeset.cost.html.md#module-mergeset.cost)               | What an evaluation costs — per validation tier, and per change.                                               |
| [`gitops`](mergeset.gitops.html.md#module-mergeset.gitops)           | Git primitives: the cheap pre-oracles and the isolated merge.                                                 |
| [`log`](mergeset.log.html.md#module-mergeset.log)                 | The evaluation log: append-only JSONL, and the single source of truth.                                        |
| [`oracle`](mergeset.oracle.html.md#module-mergeset.oracle)           | The oracle: turn a change set into a verdict by merging, then validating.                                     |
| [`report`](mergeset.report.html.md#module-mergeset.report)           | Rendering an [`Analysis`](mergeset.analysis.html.md#mergeset.analysis.Analysis) for humans. |
| [`skills`](mergeset.skills.html.md#module-mergeset.skills)           | The agent skill that ships inside the package, and how to install it.                                         |
| [`solve`](mergeset.solve.html.md#module-mergeset.solve)             | The search: from expensive yes/no evaluations to maximal good sets.                                           |
| [`sources`](mergeset.sources.html.md#module-mergeset.sources)         | Change sources: where the candidate changes come from.                                                        |
| [`stacks`](mergeset.stacks.html.md#module-mergeset.stacks)           | Stacked changes: when the candidates are not independent.                                                     |
| [`storage`](mergeset.storage.html.md#module-mergeset.storage)         | Where mergeset's artifacts live, and how code reaches them.                                                   |
| [`tiers`](mergeset.tiers.html.md#module-mergeset.tiers)             | Tiered validation: a cheap oracle screens, an expensive one confirms.                                         |
| [`validation`](mergeset.validation.html.md#module-mergeset.validation)   | Validation functions: does this merged tree actually work?                                                    |
