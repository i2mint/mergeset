# mergeset

Which of these branches can be merged together?

Given a base commit and *n* candidate changes — branches, pull requests, commits — `mergeset` finds the **maximal sets** that merge cleanly and still pass validation, and the minimal **conflicts** that stop the rest.

```bash
pip install mergeset
python -m mergeset branches feat-a feat-b feat-c --base main
```

```python
from mergeset import analyze, branch_changes, markdown_report

changes = list(branch_changes('.', ['feat-a', 'feat-b', 'feat-c'], base='main'))
print(markdown_report(analyze('.', changes)))
```

You get a merge plan: merge these, in this order, and here is what you lose — plus, for everything dropped, whether it was a textual conflict (and in which files) or a test failure (and which tests).

## Why it is not just "try every subset"

Evaluating a subset means merging it and running a test suite. That is minutes, and there are `2**n` subsets. So `mergeset` spends its evaluations the way a person would if each one cost real money.

**Ask the cheap oracles first.** Nothing expensive runs until everything free has had its say: a change whose own CI is red is a conflict of size one; `git merge-tree --write-tree` finds textual conflicts in milliseconds without ever creating a working tree; and changes touching disjoint files form independent subproblems that are solved separately and combined.

**Never evaluate the same set twice.** Every evaluation is appended to `.mergeset/evaluations.jsonl`, which is the single source of truth. Re-running is nearly free, a crashed run resumes, and reports regenerate without re-running anything. The log also propagates monotonicity: a passing set marks all its subsets good, a failing set marks all its supersets bad.

**Search like a SAT solver, not like a loop.** A failure is shrunk to a minimal conflict by QuickXplain (`O(k log n)` evaluations instead of `O(n)`), and the next candidate to try is the complement of the cheapest minimal hitting set of all conflicts found so far — Reiter's hitting-set duality, which says exactly that complements of maximal good sets *are* the minimal hitting sets of the conflicts.

**Weights mean "cost of dropping this".** When something has to go, the tool drops the cheapest work, not the first thing it thought of.

## Progressive disclosure

The call above takes no configuration and works. Every piece of it is one keyword argument away from being replaced.

| you want to change | keyword |
|---|---|
| where changes come from | `mergeset.sources` — `branch_changes`, `pr_changes`, `commit_changes`, or any iterable of `Change` |
| what counts as "works" | `validate=` — `pytest_validation()`, `command_validation('make test')`, `js_validation(...)`, `staged_validation([...])`, `act_validation()`, `callable_validation(my_func)` |
| how much it may spend | `max_evaluations=`, `max_seconds=`, `max_sets=` — partial results are always returned and labelled partial |
| what dropping a change costs | `weight=` — any `Change -> float` |
| where the log lives | `log=` / `log_path=` — anything with `append` and `__iter__` |
| conflict resolution | `resolver=claude_code_resolver()` — flagged, never silent |

## Real repositories are messier than the theory

Three things break the clean picture, and `mergeset` handles each explicitly rather than pretending.

**Stacked PRs.** A PR opened against another PR's branch already contains it, so subsets are not free: a valid set must be *downward-closed* under the parent relation — and stacks branch, so this is a forest, not a chain. `mergeset` closes sets before evaluating them, merges only the *tips* (merging a tip brings its ancestors), and charges the cost of a change's whole descendant cone when deciding what to drop. On a 15-PR forest this also cuts the search space from 32768 subsets to 576.

**A green PR that will not land.** GitHub's `mergeable` and CI status are computed against the PR's *own* base branch. If that branch has moved on, a PR can be green and "CLEAN" on GitHub and still refuse to merge onto `main`. `mergeset` ignores the forge's verdict whenever the bases disagree, and checks by actually merging.

**Monotonicity is a prior, not a law.** A change can contain the fix that makes another one work, and flaky tests break closure outright. Violations are detected and reported loudly rather than silently trusted; `flake_tolerant(validate, retries=1)` is the cheap mitigation.

## Validation is a sequence, not a command

Real projects do not have "the test command". They have an install step (slow, and only needed when the lockfile moved), a build step that is a *prerequisite* of testing rather than part of it, then tests, then lint. A single pass/fail bit throws away the distinction you most need — "failed to build" is not "tests failed".

```python
from mergeset import ValidationStage, staged_validation, file_fingerprint

validate = staged_validation([
    ValidationStage('setup', 'pnpm install --frozen-lockfile',
                    fingerprint=file_fingerprint('pnpm-lock.yaml')),
    ValidationStage('build', 'pnpm run build'),
    ValidationStage('test',  'pnpm run test'),
    ValidationStage('lint',  'pnpm run lint', required=False),
])
analyze(repo, changes, validate=validate, reuse_worktree='/tmp/scratch-wt')
```

The fingerprinted stage runs only when its inputs actually change, and `reuse_worktree` keeps one tree across the whole run — so an expensive install is paid once, not once per evaluation.

## Output

- **Markdown report** — the merge plans first, then what stops the rest, then the evidence.
- **Self-contained HTML** — one file, no build step, no network: the conflict graph (textual vs validation conflicts distinguished), the plans, and the evaluation log.
- **Integration branches** — `--integration-branches` creates a local `integration/<date>-<k>` per maximal set so you can test one by hand. It only ever creates *new local* branches; it never touches an existing branch and never pushes.

## Requirements

- Python ≥ 3.10, git ≥ 2.38 (for `git merge-tree --write-tree`; checked at startup with a message telling you how to fix it).
- `gh`, authenticated, only if you use the pull-request source.
- Whatever your validation command needs. Capabilities are checked up front rather than failing halfway through a long run.

## Reading further

`DECISIONS.md` records every non-obvious design choice and why. `RESEARCH.md` covers the MUS/MSS literature this is built on, the merge-queue prior art, and what was deliberately not depended on.
