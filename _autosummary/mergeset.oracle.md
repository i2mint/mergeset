# mergeset.oracle

The oracle: turn a change set into a verdict by merging, then validating.

This is the expensive seam of the whole package, and it is assembled from two
injected pieces — a *merge function* and a *validation function* — so that every
part of it can be replaced without touching the search.

The default merge is a plain sequential `git merge` in a throwaway worktree:
any textual conflict is a failure, and the conflicting files are recorded. An
**AI-assisted** mode is available (and is intended as the default when running
inside a Claude Code subagent): on a textual conflict a resolver may attempt a
fix under a strict policy — mechanical conflicts only, never a semantic guess —
and the result is *flagged* as “mergeable with assisted resolution” with the
resolution diff saved. It is never silently reported as a clean merge.

### Module Attributes

| [`Resolver`](#mergeset.oracle.Resolver)   | `(worktree, conflicting_files) -> (resolved?, diff)`.   |
|-------------------------------------------------------------|---------------------------------------------------------|

### Functions

| [`claude_code_resolver`](#mergeset.oracle.claude_code_resolver)(\*[, timeout, command])   | Resolve conflicts with a Claude Code subagent, under a strict policy.   |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`git_oracle`](#mergeset.oracle.git_oracle)(repo, base, changes, \*[, ...])     | Build the evaluator: merge the set onto `base`, then validate the tree. |
| [`merge_order`](#mergeset.oracle.merge_order)(subset, changes)                   | A deterministic merge order for a change set.                           |

### mergeset.oracle.Resolver

`(worktree, conflicting_files) -> (resolved?, diff)`.

* **Type:**
  A resolver

alias of `Callable`[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]], `Tuple`[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### mergeset.oracle.claude_code_resolver(, timeout=300.0, command='claude')

Resolve conflicts with a Claude Code subagent, under a strict policy.

The policy is in the prompt and is deliberately narrow: mechanical conflicts
only (import blocks, changelog entries, adjacent independent edits, lockfile
regeneration), and an explicit refusal whenever the resolution requires
guessing intent. Anything it does resolve is flagged and its diff kept.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]], [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### mergeset.oracle.git_oracle(repo, base, changes, , validate=None, resolver=None, depends_on=None, reuse_worktree=None, worktree_root=None, keep_worktrees=False, on_event=None)

Build the evaluator: merge the set onto `base`, then validate the tree.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Path to the git repository (worktrees are created off it).
  * **base** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The commit everything is merged onto.
  * **changes** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Change`](mergeset.base.md#mergeset.base.Change)]) – The changes in play; only their ids are passed around later.
  * **validate** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`ValidationOutcome`](mergeset.base.md#mergeset.base.ValidationOutcome)]]) – `worktree -> ValidationOutcome`. Defaults to a fail-fast
    pytest run; see [`mergeset.validation`](mergeset.validation.md#module-mergeset.validation) for the alternatives.
  * **resolver** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]], [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – Optional AI-assisted conflict resolver. When given, a textual
    conflict is offered to it once; a success is recorded with
    `merge.assisted = True` and the diff kept.
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
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)], [`Evaluation`](mergeset.base.md#mergeset.base.Evaluation)]
* **Returns:**
  `evaluate(subset) -> Evaluation`. Wrap it in
  `EvaluationLog.caching` before handing it to the solver.

### mergeset.oracle.merge_order(subset, changes)

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
