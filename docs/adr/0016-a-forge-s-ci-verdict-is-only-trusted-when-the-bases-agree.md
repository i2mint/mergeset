---
adr: 0016
decision: D16   # the identifier this was published under before the split
title: "A forge's CI verdict is only trusted when the bases agree"
status: accepted
found_by: TEST workstream
---

# 0016 — A forge's CI verdict is only trusted when the bases agree

> Found by the TEST workstream during the trial run.

GitHub reported PR-07 as `MERGEABLE` / `CLEAN` while it would not merge onto `main` at all — because GitHub was evaluating it against its own base branch, which had moved on. `analyze` compares each change's `base_ref` against the base being merged onto and ignores the forge's signal when they differ, saying so in the report. TEST rates this the single highest-value cheap check in the run: it excluded one change and its whole cone before any test.
