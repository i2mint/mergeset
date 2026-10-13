---
adr: 0028
title: "A log row is about the commits that were merged, not about the change ids"
status: accepted
---

# 0028 — A log row is about the commits that were merged, not about the change ids

A cache hit used to be matched on the set of change **ids**. Rewriting a branch and keeping its id (resolving a conflict, merging a base into it) left every row about the old head answering for the new one. On a real 15-PR set this reported `CONFLICT: ['pr560', 'pr587']` for a pair that could not conflict — `pr587` had become an ancestor of the new `pr560` — and the opposite direction, a stale PASS reported as a validated set, was equally possible and invisible (i2mint/mergeset#23).

**Decision.** Every `Evaluation` row records `base_sha` and `heads` (change id → full head sha). `analyze` resolves every head to a sha once, merges those shas rather than the refs (so a branch moving mid-run cannot put unrecorded commits under a pinned row), and pins the log to them with `EvaluationLog.pin(base=, heads=)`. A pinned log counts a row only when its base matches and every change it holds that is in play had the same head; changes in the row that are not in play do not matter, which keeps the monotone closure over an earlier, larger candidate set. `analyze_tiered` pins every tier's log, not just the screen's.

**Rows that do not match are kept.** They are not wrong, they answer a different question, so they stay in the store and in `EvaluationLog.rows`, are listed by `stale`, and the analysis says how many were set aside. Throwing the whole log away to invalidate two rows was the workaround this replaces.

**Old logs.** Rows written before this record no commits. They still load (nothing is dropped, nothing is rewritten), are listed by `unpinned`, and are *not* trusted by a pinned log by default, because a row that may be about a moved head is exactly the defect. `EvaluationLog(..., trust_unpinned=True)` adopts them when the user knows the heads have not moved; the analysis note names that switch. An unpinned log (no `pin` call) behaves exactly as before.

**Not covered.** The validator's own configuration is not part of the key; tiers keep separate logs for that reason (ADR 0026), and a changed validation command under one log is still the user's to notice. Cost measurements read every row, pinned or not: what an evaluation cost is a fact about the tier, not about one head.
