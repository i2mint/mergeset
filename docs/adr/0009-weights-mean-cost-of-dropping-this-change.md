---
adr: 0009
decision: D9   # the identifier this was published under before the split
title: "Weights mean 'cost of dropping this change'"
status: accepted
---

# 0009 — Weights mean "cost of dropping this change"

The hitting set is weighted so that when something must be dropped, the tool drops the *cheapest* work. Default weight is `1 + log1p(lines changed)`: bigger changes are worth more, log-shaped so one huge branch cannot dominate. Overridable with any `Change -> float`, and PR metadata (labels, author, age) is right there in `change.meta` for a policy that wants it.
