---
adr: 0021
decision: D21   # the identifier this was published under before the split
title: "An empty log is still a log"
status: accepted
---

# 0021 — An empty log is still a log

`log = log or EvaluationLog(...)` silently discarded a caller-supplied log, because `__len__` makes an empty one falsy — on the first run, which is the run where it matters. `EvaluationLog.__bool__` now returns True, and the call site tests `is None`.
