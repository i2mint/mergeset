# mergeset.sources

Change sources: where the candidate changes come from.

A **source** is any callable returning an iterable of [`Change`](mergeset.base.html.md#mergeset.base.Change).
Branches, pull requests and explicit commit lists are just different sources of
the same thing — a `base..head` range — which is why the rest of the package
never mentions the word “PR”.

PR sources carry the extra metadata that only a forge knows (author, title, CI
status, base branch, draft flag, stack relationships); it rides along in
`Change.meta` and is used for weighting and for the report, never by the
solver.

### Module Attributes

| [`PR_FIELDS`](#mergeset.sources.PR_FIELDS)   | Fields worth asking `gh` for; anything else is noise in the report.   |
|--------------------------------------------------------------|-----------------------------------------------------------------------|

### Functions

| [`branch_changes`](#mergeset.sources.branch_changes)(repo, branches, \*[, base, prefix])   | Changes from local or remote branches.                                |
|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`check_gh_capability`](#mergeset.sources.check_gh_capability)()                                | Raise a fixable error if the GitHub CLI is unusable.                  |
| [`commit_changes`](#mergeset.sources.commit_changes)(repo, commits, \*[, base])            | Changes from an explicit list of commit-ishes, one change per commit. |
| [`detect_stacks`](#mergeset.sources.detect_stacks)(changes)                               | Map change id -> the change id it is stacked on, for PR stacks.       |
| [`fetch_pull_requests`](#mergeset.sources.fetch_pull_requests)(repo_spec, \*[, author, ...])    | Raw `gh pr list` records for `repo_spec` (`owner/name`).              |
| [`local_branch_names`](#mergeset.sources.local_branch_names)(repo, \*[, pattern, exclude])     | Local branch names, optionally filtered by a glob `pattern`.          |
| [`pr_changes`](#mergeset.sources.pr_changes)(repo, pull_requests, \*[, base, ...])     | Turn `gh pr list` records into changes.                               |
| [`size_weight`](#mergeset.sources.size_weight)(repo, change)                            | Default weight: how much it costs to drop this change.                |

### mergeset.sources.PR_FIELDS *= 'number,title,author,headRefName,baseRefName,isDraft,updatedAt,createdAt,state,mergeable,statusCheckRollup,url,additions,deletions,changedFiles'*

Fields worth asking `gh` for; anything else is noise in the report.

### mergeset.sources.branch_changes(repo, branches, , base='HEAD', prefix='')

Changes from local or remote branches.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]

```pycon
>>> list(branch_changes('.', []))
[]
```

### mergeset.sources.check_gh_capability()

Raise a fixable error if the GitHub CLI is unusable.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### mergeset.sources.commit_changes(repo, commits, , base='HEAD')

Changes from an explicit list of commit-ishes, one change per commit.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]

### mergeset.sources.detect_stacks(changes)

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

### mergeset.sources.fetch_pull_requests(repo_spec, , author=None, state='open', limit=100, extra_args=())

Raw `gh pr list` records for `repo_spec` (`owner/name`).

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### mergeset.sources.local_branch_names(repo, , pattern=None, exclude=())

Local branch names, optionally filtered by a glob `pattern`.

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.sources.pr_changes(repo, pull_requests, , base=None, ref_of=None)

Turn `gh pr list` records into changes.

* **Parameters:**
  * **repo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Local clone the refs live in.
  * **pull_requests** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Records as produced by [`fetch_pull_requests()`](#mergeset.sources.fetch_pull_requests).
  * **base** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Override base for every change. Default: each PR’s own base ref,
    which is what makes stacked PRs visible rather than silently wrong.
  * **ref_of** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – How to name a PR’s head ref locally. Default `origin/<headRef>`.
* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Change`](mergeset.base.html.md#mergeset.base.Change)]

### mergeset.sources.size_weight(repo, change)

Default weight: how much it costs to drop this change.

Bigger changes are worth more (dropping a 900-line PR wastes more work than
dropping a typo fix), so the weighted hitting set prefers to drop the small
ones. `log`-shaped so one huge branch does not dominate everything.

Override with any `Change -> float`; PR metadata (priority labels,
author, age) is right there in `change.meta` for the taking.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
