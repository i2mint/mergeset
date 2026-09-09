---
adr: 0022
decision: D22   # the identifier this was published under before the split
title: "The CLI can describe a real project, not only an easy one"
status: accepted
found_by: TEST workstream
---

# 0022 — The CLI can describe a real project, not only an easy one

> Found by the TEST workstream during the trial run.

TEST's verification run reached the hand-derived answer exactly, and then reported the gap that mattered: the CLI could offer only `--merge-only`, one `--validate-command` string, or pytest. For the repository under test, the only expressible option was chaining install && build && test && lint into a single string, which throws away everything the staged validator exists for.

So `--validate-stage 'name:command'` is repeatable and ordered, `--validate-fingerprint 'stage:path'` makes a stage skippable, `--validate-optional name` makes one advisory, and `--reuse-worktree` is now a CLI flag too — without it the fingerprint has nothing to persist across. `--validate-command` remains the shorthand. The point is stated in the docs as well as the code: a chained string costs a re-run of the install per evaluation, collapses build and test failures into one exit code, and turns an advisory lint into a veto.

**And a correction while implementing it:** `required=False` used to record a stage's failure *and still fail the set*, which made the flag nearly useless — an advisory lint would have excluded every candidate. A non-required stage's failure is now recorded in `failing_tests` while the set still counts as good.
