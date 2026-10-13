---
adr: 0028
title: "A log row is about the commits that were merged, not about the change ids"
status: accepted
---

# 0028 — A log row is about the commits that were merged, not about the change ids

A cache hit used to be matched on the set of change **ids**. Rewriting a branch and keeping its id (resolving a conflict, merging a base into it) left every row about the old head answering for the new one. On a real 15-PR set this reported `CONFLICT: ['pr560', 'pr587']` for a pair that could not conflict — `pr587` had become an ancestor of the new `pr560` — and the opposite direction, a stale PASS reported as a validated set, was equally possible and invisible (i2mint/mergeset#23).

**Decision.** Every `Evaluation` row records `base_sha` and `heads` (change id → full head sha). `analyze` resolves every head to a sha once, and everything after that — changed files, the textual pre-oracles, the oracle, every tier's oracle, integration branches — uses the shas, never the refs, so a branch moving mid-run cannot put unrecorded commits under a pinned row. The log is then scoped with `EvaluationLog.pinned(base=, heads=)`, a *view* over the same rows: a log the caller hands to two analyses is not re-scoped under the first. A pinned view counts a row only when its base matches and every change it holds is in play at the same head. A row holding a change that is not in play does not count: its head for that change is unchecked, and counting it surfaced that change in an "established" fallback set and produced monotonicity violations between two heads of it. `analyze_tiered` pins every tier's log, not just the screen's.

**Stacks are checked against git, not only metadata.** A stack edge from PR metadata lets the oracle merge only the child, since the child contains the parent. When the parent moved and the child was not rebased, that is false: the tree held the parent's old head while the row named its new one, which is a stale green by another route. Only edges where the parent's head is an ancestor of the child's (`Analysis.merged_through`) let the oracle skip the parent; otherwise the parent is merged explicitly and the analysis says so. The search still treats the pair as stacked.

**Rows that do not match are kept.** They are not wrong, they answer a different question, so they stay in the store and in `EvaluationLog.rows`, are listed by `stale`, and the analysis says how many were set aside. Throwing the whole log away to invalidate two rows was the workaround this replaces.

**Old logs.** Rows written before this record no commits. They still load (nothing is dropped, nothing is rewritten), are listed by `unpinned`, and are *not* trusted by a pinned log by default, because a row that may be about a moved head is exactly the defect. `trust_unpinned=True` adopts them when the user knows the heads have not moved: on `EvaluationLog`, on `analyze` and `analyze_tiered` (every tier's log), and as `--trust-unpinned-log` on the command line; the analysis note names the switch. An unpinned log (no `pin` call) behaves exactly as before.

**Not covered.** The validator's own configuration is not part of the key; tiers keep separate logs for that reason (ADR 0026), and a changed validation command under one log is still the user's to notice. The cost model learns from every row, pinned or not, because what an evaluation cost is a fact about the tier, not about one head. The `spent` a tier reports sums only the rows that count, the same rows `runs` counts. `show_log` has no candidate set to pin to, so it shows every row with its base and warns when rows disagree about commits.
