# mergeset.gitops

Git primitives: the cheap pre-oracles and the isolated merge.

Two very different costs live here, and keeping them apart is the point:

- **Cheap** (milliseconds, no working tree): `git merge-tree --write-tree`
  answers “do these two changes conflict textually?” and `git diff --name-only`
  answers “which files does this change touch?”. Everything these two can decide
  must never reach the expensive oracle.
- **Expensive** (seconds to minutes): actually materializing a merged tree in a
  throwaway worktree so a test suite can run on it.

### Module Attributes

| [`MIN_GIT_VERSION`](#mergeset.gitops.MIN_GIT_VERSION)   | `git merge-tree --write-tree` needs this; it is also when `--merge-base` landed.   |
|--------------------------------------------------------------------|------------------------------------------------------------------------------------|

### Functions

| [`changed_files`](#mergeset.gitops.changed_files)(repo, base, head)                  | Files a change touches, as `git diff --name-only base...head`.           |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`check_git_capability`](#mergeset.gitops.check_git_capability)()                           | Raise a fixable error if git is missing or too old for `merge-tree`.     |
| [`create_integration_branch`](#mergeset.gitops.create_integration_branch)(repo, name, base, ...) | Create a local branch holding `base` + all heads, for manual testing.    |
| [`git`](#mergeset.gitops.git)(repo, \*args[, check, timeout])              | Run `git -C repo *args` and capture its output.                          |
| [`git_version`](#mergeset.gitops.git_version)()                                    | The installed git version as a tuple, e.g. `(2, 50, 1)`.                 |
| [`is_ancestor`](#mergeset.gitops.is_ancestor)(repo, ancestor, descendant)          | True iff `ancestor` is reachable from `descendant` (or equal to it).     |
| [`merge_base`](#mergeset.gitops.merge_base)(repo, a, b)                           | Best common ancestor of `a` and `b`.                                     |
| [`merge_sequence`](#mergeset.gitops.merge_sequence)(repo, base, heads)                | Merge every head onto `base`, one at a time, without any worktree.       |
| [`merged_worktree`](#mergeset.gitops.merged_worktree)(repo, base, heads, \*[, ...])    | Materialize `base` plus every head in a worktree, ready for validation.  |
| [`pairwise_textual_conflicts`](#mergeset.gitops.pairwise_textual_conflicts)(repo, base, heads)    | Yield `(id_a, id_b, files)` for every pair that conflicts textually.     |
| [`persistent_worktree`](#mergeset.gitops.persistent_worktree)(repo, base, path)            | Create (once) a worktree meant to be reused across many evaluations.     |
| [`resolve`](#mergeset.gitops.resolve)(repo, rev)                               | Full sha of `rev`.                                                       |
| [`singleton_textual_conflicts`](#mergeset.gitops.singleton_textual_conflicts)(repo, base, heads)   | Yield `(id, files)` for every change that will not even merge onto base. |
| [`textual_conflict`](#mergeset.gitops.textual_conflict)(repo, base, head_a, head_b)     | Conflicting files if merging both heads onto `base` clashes textually.   |

### Classes

| [`GitResult`](#mergeset.gitops.GitResult)(returncode, stdout, stderr)   | Raw result of one git invocation.                                      |
|------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`SequenceMerge`](#mergeset.gitops.SequenceMerge)(ok[, commit, ...])        | Result of merging changes onto a base entirely in the object database. |

### *class* mergeset.gitops.GitResult(returncode, stdout, stderr)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Raw result of one git invocation.

#### *property* ok *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True iff git exited 0.

### mergeset.gitops.MIN_GIT_VERSION *= (2, 38)*

`git merge-tree --write-tree` needs this; it is also when `--merge-base` landed.

### *class* mergeset.gitops.SequenceMerge(ok, commit=None, conflicting_files=(), order=(), detail='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Result of merging changes onto a base entirely in the object database.

#### commit *: [str](https://docs.python.org/3/builtins/stdtypes.html#str) | [None](https://docs.python.org/3/builtins/constants.html#None)* *= None*

Commit holding base + every merged head, when the whole sequence was clean.

#### order *: [Sequence](https://docs.python.org/3/library/typing.html#typing.Sequence)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= ()*

The changes merged so far; the last one is the one that conflicted.

### mergeset.gitops.changed_files(repo, base, head)

Files a change touches, as `git diff --name-only base...head`.

The three-dot form is deliberate: it compares against the merge base, so a
change is measured by what *it* did, not by what happened on base meanwhile.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.gitops.check_git_capability()

Raise a fixable error if git is missing or too old for `merge-tree`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### mergeset.gitops.create_integration_branch(repo, name, base, heads, , force=False)

Create a local branch holding `base` + all heads, for manual testing.

Only ever creates *new* local branches. Never touches an existing branch
unless `force` is passed explicitly, and never pushes anything.

* **Return type:**
  [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  `(created, message)`.

### mergeset.gitops.git(repo, \*args, check=False, timeout=None)

Run `git -C repo *args` and capture its output.

* **Return type:**
  [`GitResult`](#mergeset.gitops.GitResult)

```pycon
>>> git('.', 'rev-parse', '--git-dir').ok in (True, False)
True
```

### mergeset.gitops.git_version()

The installed git version as a tuple, e.g. `(2, 50, 1)`.

* **Return type:**
  [`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### mergeset.gitops.is_ancestor(repo, ancestor, descendant)

True iff `ancestor` is reachable from `descendant` (or equal to it).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### mergeset.gitops.merge_base(repo, a, b)

Best common ancestor of `a` and `b`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.gitops.merge_sequence(repo, base, heads)

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
  [`SequenceMerge`](#mergeset.gitops.SequenceMerge)

### mergeset.gitops.merged_worktree(repo, base, heads, , root=None, keep=False, reuse=None)

Materialize `base` plus every head in a worktree, ready for validation.

The merge itself happens in the object database ([`merge_sequence()`](#mergeset.gitops.merge_sequence)), so
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

### mergeset.gitops.pairwise_textual_conflicts(repo, base, heads)

Yield `(id_a, id_b, files)` for every pair that conflicts textually.

`heads` maps change id -> commit-ish. This is the pre-oracle that buys the
most: every pair it finds is a size-2 conflict known before any test runs.
Each pair is merged *onto base*, never against each other — see
[`textual_conflict()`](#mergeset.gitops.textual_conflict) for why that distinction is not cosmetic.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]

### mergeset.gitops.persistent_worktree(repo, base, path)

Create (once) a worktree meant to be reused across many evaluations.

Reusing one tree is what makes an expensive setup step amortizable: install
dependencies once, then check out each candidate merge into the same
directory. Returns `path`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.gitops.resolve(repo, rev)

Full sha of `rev`.

* **Raises:**
  [**CapabilityError**](mergeset.html.md#mergeset.CapabilityError) – if the revision cannot be resolved in `repo`.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.gitops.singleton_textual_conflicts(repo, base, heads)

Yield `(id, files)` for every change that will not even merge onto base.

The cheapest check there is, and on real PR sets it fires more than you would
expect: a PR opened against a base branch that has since moved on is green on
GitHub and still unmergeable onto the base you actually care about.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Tuple`](https://docs.python.org/3/library/typing.html#typing.Tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]

### mergeset.gitops.textual_conflict(repo, base, head_a, head_b)

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
