---
adr: 0010
decision: D10   # the identifier this was published under before the split
title: "The oracle returns a record, not a bit"
status: accepted
---

# 0010 — The oracle returns a record, not a bit

Every evaluation returns which tests failed, which files they live in, the merge order used, the conflicting paths and the duration. The solver uses the merge outcome's attribution to aim `quickxplain` at the changes actually implicated instead of halving blindly, and the report can say *why* two changes conflict rather than only *that* they do. Returning a bit would have been simpler and would have thrown away the most useful thing an expensive run produces.
