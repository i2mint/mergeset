# mergeset.analysis

The facade: one call that goes from a repository to a merge plan.

`analyze` is the “simple thing made simple” entry point. It wires together the
pieces — sources, cheap pre-oracles, file-overlap decomposition, the expensive
oracle, the log, the search — with defaults that work out of the box, and every
piece stays replaceable by one keyword argument.

The order of operations is the whole point, because it is the order of *cost*:

1. free: per-change CI status (a red singleton is a conflict of size one);
2. milliseconds: pairwise `git merge-tree` textual conflicts;
3. milliseconds: file-overlap components — independent subproblems;
4. minutes each: the real merge-and-test oracle, only on what is left.

### Functions

| [`analyze`](#mergeset.analysis.analyze)(repo, changes, \*[, base, validate, ...])   | Find the maximal sets of `changes` that merge and validate on `base`.   |
|------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`unmatched_log_notes`](#mergeset.analysis.unmatched_log_notes)(log, \*[, label])               | Say how many rows a pinned log is keeping but not using, and why.       |

### Classes

| [`Analysis`](#mergeset.analysis.Analysis)(repo, base, base_sha, changes[, ...])   | Everything a run learned.   |
|---------------------------------------------------------------------------------------------------|-----------------------------|

### *class* mergeset.analysis.Analysis(repo, base, base_sha, changes, head_shas=<factory>, maximal_sets=<factory>, conflicts=<factory>, textual_conflicts=<factory>, components=<factory>, files_by_change=<factory>, stacks=<factory>, merged_through=<factory>, weights=<factory>, own_weights=<factory>, singleton_conflicts=<factory>, components_combined=False, unverified_sets=<factory>, log=None, searches=<factory>, notes=<factory>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Everything a run learned. Every field is derivable from `log` + git.

#### *property* by_id *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Change](mergeset.base.md#mergeset.base.Change)]*

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
misleading in a report. See [`evaluations`](#mergeset.analysis.Analysis.evaluations).

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

#### *property* pinned_changes *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[Change](mergeset.base.md#mergeset.base.Change)]*

The changes with `head` replaced by the sha it resolved to.

A branch that moves mid-run must not have its new commits merged under
a row pinned to the old ones; merging the resolved shas rules that out.

#### singleton_conflicts *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [List](https://docs.python.org/3/library/typing.html#typing.List)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]]*

Changes that will not even merge onto base alone -> conflicting files.

#### unverified_sets *: [List](https://docs.python.org/3/library/typing.html#typing.List)[[frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]*

Sets reported without ever having been evaluated as a whole. Empty is the
normal case. See [`merge_plan()`](#mergeset.analysis.Analysis.merge_plan)’s `verified` and ADR 0025.

#### weights *: [Dict](https://docs.python.org/3/library/typing.html#typing.Dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]*

Cost of dropping each change *including its descendant cone*.

### mergeset.analysis.analyze(repo, changes, , base=None, validate=None, resolver=None, log=None, log_path=None, trust_unpinned=None, artifacts=None, weight=None, pairwise_preoracle=True, decompose=True, component_local=None, use_ci_status=True, check_base=True, max_evaluations=None, max_seconds=None, max_sets=None, worktree_root=None, reuse_worktree=None, on_event=None)

Find the maximal sets of `changes` that merge and validate on `base`.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to the git repository.
  * **changes** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`Change`](mergeset.base.md#mergeset.base.Change)]) – Candidate changes (see [`mergeset.sources`](mergeset.sources.md#module-mergeset.sources)).
  * **base** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – What to merge onto. Default: the merge base of every change’s own
    base, which is the only choice that is fair to all of them.
  * **validate** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.md#mergeset.base.ValidationOutcome)]]) – `worktree -> ValidationOutcome`; default is a fail-fast
    pytest run. Pass `merge_only_validation()` for a free first pass.
  * **resolver** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]], [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – Optional AI-assisted conflict resolver (results are flagged).
  * **artifacts** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)]]) – The artifact stores, as a `{kind: MutableMapping}` mall (see
    [`mergeset.storage.artifact_mall()`](mergeset.storage.md#mergeset.storage.artifact_mall)). This is the storage seam:
    pass a mall over S3 and the evaluation log goes to S3 with no other
    change. Default: local files under `~/.local/share/mergeset/`.
  * **log_path** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The evaluation log — the single source of truth. Defaults
    to `<artifact root>/evaluations/<repo-slug>.jsonl` (see
    [`mergeset.storage`](mergeset.storage.md#module-mergeset.storage)), *outside* the analysed repository. Reusing
    an existing one makes a re-run nearly free. Only rows evaluated
    against the same base and heads are reused (see ADR 0028).
  * **trust_unpinned** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Reuse log rows written before rows recorded their
    commits (an old log). Default: the log’s own setting, which is off.
    Only when the heads have not moved since those rows were written.
  * **weight** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Change`](mergeset.base.md#mergeset.base.Change)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `Change -> cost of dropping it`; default is size-based.
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
    to declare it, as [`merge_only_validation()`](mergeset.validation.md#mergeset.validation.merge_only_validation)
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
    [`mergeset.validation.staged_validation()`](mergeset.validation.md#mergeset.validation.staged_validation).
  * **on_event** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]]) – `(event, payload)` progress callback.
* **Return type:**
  [`Analysis`](#mergeset.analysis.Analysis)
* **Returns:**
  An [`Analysis`](#mergeset.analysis.Analysis).

### mergeset.analysis.unmatched_log_notes(log, , label='')

Say how many rows a pinned log is keeping but not using, and why.

Rows about other commits are never dropped, and never silently ignored
either: a re-run that is suddenly slow should say it is because heads moved.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
