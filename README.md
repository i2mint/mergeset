# mergeset

Which of these branches can be merged together?

Given a base commit and *n* candidate changes — branches, pull requests, commits — `mergeset` finds the **maximal sets** that merge cleanly and still pass validation, and the minimal **conflicts** that stop the rest.

```bash
pip install mergeset
python -m mergeset branches feat-a feat-b feat-c --base main
```

```python
from mergeset import analyze, branch_changes, markdown_report

changes = list(branch_changes(".", ["feat-a", "feat-b", "feat-c"], base="main"))
print(markdown_report(analyze(".", changes)))
```

You get a merge plan: merge these, in this order, and here is what you lose — plus, for everything dropped, whether it was a textual conflict (and in which files) or a test failure (and which tests).

## Why it is not just "try every subset"

Evaluating a subset means merging it and running a test suite. That is minutes, and there are `2**n` subsets. So `mergeset` spends its evaluations the way a person would if each one cost real money.

**Ask the cheap oracles first.** Nothing expensive runs until everything free has had its say: a change whose own CI is red is a conflict of size one; `git merge-tree --write-tree` finds textual conflicts in milliseconds without ever creating a working tree; and changes touching disjoint files form independent subproblems that are solved separately and combined.

**Never evaluate the same set twice.** Every evaluation is appended to `~/.local/share/mergeset/evaluations/<repo>.jsonl`, which is the single source of truth. Re-running is nearly free, a crashed run resumes, and reports regenerate without re-running anything. The log also propagates monotonicity: a passing set marks all its subsets good, a failing set marks all its supersets bad.

**Search like a SAT solver, not like a loop.** A failure is shrunk to a minimal conflict by QuickXplain (`O(k log n)` evaluations instead of `O(n)`), and the next candidate to try is the complement of the cheapest minimal hitting set of all conflicts found so far — Reiter's hitting-set duality, which says exactly that complements of maximal good sets *are* the minimal hitting sets of the conflicts.

**Weights mean "cost of dropping this".** When something has to go, the tool drops the cheapest work, not the first thing it thought of.

## Where the output goes

Reports, evaluation logs, raw validation output and captured fixtures all land in an **artifact store**, never in a repository:

```
~/.local/share/mergeset/            # $MERGESET_DATA_DIR overrides the root
    reports/<repo>/<timestamp>/     # REPORT.md, report.html — one key per run
    evaluations/<repo>.jsonl        # the append-only log — the source of truth
    logs/                           # raw build/test/lint output
    fixtures/                       # captured failures kept as regression tests
```

This is not tidiness. Everything `mergeset` produces is **captured from the repository it analysed** — source paths, symbol names, stack traces with verbatim code, branch names, PR metadata. Written into that repository (or into `mergeset`'s own), one `git add .` publishes it. This project has already published a private repository's internals to a public one exactly that way, so the default is now a location no `git add` can reach.

Each kind is a plain `MutableMapping[str, str]`, so the backend is one keyword argument:

```python
from mergeset import analyze, artifact_mall

# Local files, the default:
analyze(repo, changes)

# The same run, with every artifact in S3 — one keyword argument, no other change:
s3 = artifact_mall(store_factory=lambda kind, root: S3Store(bucket, prefix=kind))
analyze(repo, changes, artifacts=s3)
```

A factory is handed the **kind and the root separately**, never a joined filesystem path: a backend with no filesystem should not have to parse one out.

`--report-dir` still writes wherever you point it — an explicit choice, not a default. Without it, each run gets its own key, so re-analysing a repository never overwrites the answer you are comparing against.

Reports render as Markdown and HTML by default, and PDF on request:

```bash
python -m mergeset prs OWNER/REPO --report-format markdown html pdf   # needs mergeset[pdf]
```

The PDF is rendered from the Markdown, not the HTML — the HTML report draws itself from an embedded JSON blob at load time, so a print pipeline that does not run JavaScript would give you a blank page that looks fine until someone opens it.

## Progressive disclosure

The call above takes no configuration and works. Every piece of it is one keyword argument away from being replaced.

| you want to change | keyword |
|---|---|
| where changes come from | `mergeset.sources` — `branch_changes`, `pr_changes`, `commit_changes`, or any iterable of `Change` |
| where artifacts are kept | `mergeset.storage` — `artifact_store(kind, store_factory=...)`; local files by default, S3 by passing a different factory |
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

From the CLI, the same thing, repeatable and ordered:

```bash
python -m mergeset prs OWNER/REPO --repo . \
    --validate-stage 'setup:pnpm install --frozen-lockfile' \
                     'build:pnpm run build' \
                     'test:pnpm run test' \
                     'lint:pnpm run lint' \
    --validate-fingerprint 'setup:pnpm-lock.yaml' \
    --validate-optional lint \
    --reuse-worktree /tmp/mergeset-wt
```

An optional stage's failure is recorded but does not veto the set — for a lint the project runs as a separate job rather than a gate. From the library:

```python
from mergeset import ValidationStage, staged_validation, file_fingerprint

validate = staged_validation(
    [
        ValidationStage(
            "setup",
            "pnpm install --frozen-lockfile",
            fingerprint=file_fingerprint("pnpm-lock.yaml"),
        ),
        ValidationStage("build", "pnpm run build"),
        ValidationStage("test", "pnpm run test"),
        ValidationStage("lint", "pnpm run lint", required=False),
    ]
)
analyze(repo, changes, validate=validate, reuse_worktree="/tmp/scratch-wt")
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

[`docs/adr/`](docs/adr/README.md) records every non-obvious design choice and why — one numbered ADR per decision, with an index. [`docs/RESEARCH.md`](docs/RESEARCH.md) covers the MUS/MSS literature this is built on, the merge-queue prior art, and what was deliberately not depended on.
