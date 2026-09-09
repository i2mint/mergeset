---
adr: 0014
decision: D14   # the identifier this was published under before the split
title: "Validation is an ordered sequence of named stages"
status: accepted
found_by: TEST workstream
---

# 0014 — Validation is an ordered sequence of named stages

> Found by the TEST workstream during the trial run.

Real projects do not have "the test command". On the repository TEST measured, `pnpm run build:cosmos` is a *prerequisite* of testing — without it seven test files fail to collect — so a validator that ran only the test command would report a false failure. And the expensive step is not the tests (9 s) but the install (33 s), which only needs to run when the lockfile moves.

So a validator is a list of `ValidationStage(name, command, fingerprint=, required=)`. The failing stage's name is prefixed onto every failure id, keeping "failed to build" distinguishable from "tests failed" in the log; a fingerprinted stage re-runs only when its inputs change; and `reuse_worktree=` keeps one tree for the whole run so the install is amortized. Lint is a non-required stage by default, matching how the repository's own CI gates.
