---
name: mergeset
description: Work out which branches or pull requests can be merged together, and in what order. Use when several changes are in flight on one repository and someone asks which of them can land together, what conflicts with what and why, whether a set of branches can be merged, why two changes cannot go together, or for a landing plan and integration branches. Also use to read or explain an existing mergeset report or evaluation log.
---

# mergeset

Finds the maximal sets of changes that merge cleanly and still validate, and the minimal conflicts that stop the rest.

## Do the cheap thing first

Every expensive step is a merge plus a test run. The order below is the order of cost, and skipping ahead wastes minutes per step.

```bash
# 1. free: textual conflicts, stacks, changes that cannot merge onto base at all
python -m mergeset branches feat-a feat-b feat-c --base main --merge-only

# 2. the same for PRs, with the forge metadata
python -m mergeset prs OWNER/REPO --repo . --author USER --updated-within-hours 48 --merge-only

# 3. only now, with the project's real command and a budget
python -m mergeset prs OWNER/REPO --repo . --validate-command 'pnpm run test' \
    --max-seconds 3600 --integration-branches

# ...or, when validation is a sequence rather than one command (it usually is)
python -m mergeset prs OWNER/REPO --repo . \
    --validate-stage 'setup:pnpm install --frozen-lockfile' \
                     'build:pnpm run build' 'test:pnpm run test' 'lint:pnpm run lint' \
    --validate-fingerprint 'setup:pnpm-lock.yaml' \
    --validate-optional lint \
    --reuse-worktree /tmp/mergeset-wt --max-seconds 3600
```

Do not chain a sequence into one `--validate-command` string. It costs you the three things that matter: the setup stage stops being skippable (a dependency install on every evaluation), build and test failures collapse into one exit code, and an advisory lint becomes a veto.

`--merge-only` costs seconds and usually finds most of the conflicts. Read that report before spending anything.

## Use the library when the project needs more than one command

```python
from mergeset import (
    analyze,
    fetch_pull_requests,
    pr_changes,
    staged_validation,
    ValidationStage,
    file_fingerprint,
    markdown_report,
    html_report,
)

validate = staged_validation(
    [
        ValidationStage(
            "setup",
            "pnpm install --frozen-lockfile",
            fingerprint=file_fingerprint("pnpm-lock.yaml"),
        ),
        ValidationStage("build", "pnpm run build"),  # a prerequisite, not a test
        ValidationStage("test", "pnpm run test"),
        ValidationStage("lint", "pnpm run lint", required=False),
    ]
)

prs = fetch_pull_requests("owner/repo", author="someone")
analysis = analyze(
    ".",
    list(pr_changes(".", prs)),
    base="origin/main",
    validate=validate,
    reuse_worktree="/tmp/mergeset-wt",  # install paid once, not per evaluation
    max_seconds=3600,
)
print(markdown_report(analysis))
```

`analysis.merge_plan()` gives, per set: `merge` (the refs to actually merge — stack tips only), `changes` (everything that lands), `dropped`, and the weights.

## Never do

Merge into a default branch, push to an existing branch, force-push, or delete a remote ref. `mergeset` only ever creates *new local* branches; keep it that way. Hand back the plan and let a human land it.

**And never commit a run's output to a repository.** Reports, evaluation logs, raw build/test output and captured fixtures all go to the artifact store by default — `~/.local/share/mergeset/{reports,evaluations,logs,fixtures}/` — and they belong there.

Everything `mergeset` produces is captured from the repository it analysed: source paths, symbol names, stack traces printing verbatim code, branch names, PR titles, commit SHAs. So before you `git add` any of it, ask two questions in this order:

1. **Is the destination repository public?** `gh repo view <owner>/<repo> --json visibility -q .visibility`
2. **Is the analysed repository private?** `gh repo view <owner>/<analysed> --json visibility -q .visibility`

Public destination + private source → it does not go in the repo. Cite it by store path instead. This is not hypothetical: `i2mint/mergeset` published 39 files of a private repo's internals this way — to GitHub *and* to four PyPI sdists — and every step along the way looked like good practice ("the report is the deliverable", "the logs are the evidence", "the fixtures are the tests"). Removing them from HEAD did not unpublish them.

## Stop and say so when

- The report says **ABORTED**, or a note says an evaluation could not be performed — the run did not fail, it did not happen. Usually a bad `reuse_worktree` path or a wrong validation command.
- The **base does not validate on its own** — `analyze` refuses to start. Fix the base or the command; do not pass `check_base=False` to get past it.
- A **monotonicity violation** is reported — a flaky test, or a change that fixes another. The conclusions are not trustworthy until it is understood.

## Read, do not re-run

The evaluation log is the single source of truth and everything regenerates from it. It lives at `~/.local/share/mergeset/evaluations/<repo-slug>.jsonl`.

```bash
python -m mergeset show-log --repo .
```

Answer questions about an existing analysis from the log. A second run over the same sets costs nothing, but re-deriving what the log already says costs a reader's trust.

## What the output does not mean

- A green CI badge is against the PR's **own** base branch. If that is not the base you are merging onto, it says nothing — the report will say it is being ignored.
- "Mergeable with assisted resolution" is **not** a clean merge. Show the saved resolution diff and let a human decide.
- File-overlap components find conflicts cheaply; they do not prove two changes are independent. A whole-repo test run can fail on changes that share no file.
