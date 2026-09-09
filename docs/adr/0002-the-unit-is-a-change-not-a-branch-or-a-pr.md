---
adr: 0002
decision: D2   # the identifier this was published under before the split
title: "The unit is a **change**, not a branch or a PR"
status: accepted
---

# 0002 — The unit is a **change**, not a branch or a PR

A change is a commit range `base..head`. Branches, pull requests and explicit commit lists are *sources* that produce changes; a PR source additionally carries metadata (number, author, title, CI status, base ref, draft flag, stack relationship) in `Change.meta`.

The reason to pick one word and hold it: the same analysis has to serve "these five local branches", "these PRs updated in the last 48h", and "these cherry-picks", and if the vocabulary tracks the source then every function ends up with three names for one idea. Only the *sources* module knows the word "PR"; the solver, the log and the report never say it. Metadata rides along for weighting and reporting but the solver never reads it — that keeps the search honest and testable without a repository.
