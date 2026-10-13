---
adr: 0034
title: "A resolver is offered the conflicts the pre-oracle would exclude"
status: accepted
---

# 0034 — A resolver is offered the conflicts the pre-oracle would exclude

The `git merge-tree` pre-oracle (ADR 0006: cost ordering) finds every change that does not merge onto the base and every pair that conflicts textually, and seeds them as known failures before any evaluation. A resolver is only offered the conflicts that reach the merge itself, so with the pre-oracle on (the CLI default) it was offered none, and `--resolver claude` did nothing unless `--no-pairwise` was also passed (i2mint/mergeset#44).

**Decision.** When a resolver is given, `analyze` skips the pre-oracle and says so in a note. Every conflict is found by merging, where the resolver is offered it. A textual conflict is what a resolver exists for; excluding it up front answers a question nobody asked.

**Considered: keep the pre-oracle as a cost hint.** Its pairs could order the search or warn that the resolver will be needed, without being seeded. The search has no ordering seam for that today, and a list of pairs that are not conflicts would sit in `Analysis.textual_conflicts`, which every reader (the report, the tiered seeds) takes to mean excluded. Skipping is the honest version until there is a consumer for the hint.

**Reports follow.** A conflict a resolver declined is a FAIL at the merge stage. It is now listed as *Did not merge*, with its conflicting files, and drawn as a textual edge, never under "merged cleanly, still failed". The same holds for any merge-stage FAIL the pre-oracle did not foresee (three changes that conflict only together, or a run with `--no-pairwise`).
