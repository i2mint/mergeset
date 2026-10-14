---
adr: 0042
title: "Each textual conflict is offered to the resolver once, up front"
status: accepted
---

# 0042 — Each textual conflict is offered to the resolver once, up front

ADR 0034 skipped the `git merge-tree` pre-oracle when a resolver is given, so that the resolver is offered the conflicts it exists for. The cost: a resolver that declines a pair was asked again for every evaluated superset holding it, before the search narrowed to the pair (a probe with 11 branches and 3 conflicting pairs made 14 resolver calls with decompose off). Each call is slow and paid (i2mint/mergeset#47).

**Decision.** With a resolver and `pairwise_preoracle=None`, the pre-oracle still runs (milliseconds, no worktree). Its singletons and pairs are not seeded. After the base check and before the search, each one is evaluated once through the caching oracle (`_offer_once`), singletons first, skipping pairs that hold a declined singleton. Only the sets that FAIL are seeded as known conflicts; a set the resolver resolved PASSes and stays in play. The search re-uses these evaluations from the log. At most one resolver call per pair.

- `Analysis.textual_conflicts` stays empty in this mode: it means "excluded before any test ran", and readers (the report, tiered seeds) rely on it. A declined pair is reported as *Did not merge* from the log, as in ADR 0034.
- The offering spends from `max_evaluations` / `max_seconds`; the search gets the remainder. An exhausted budget stops the offering and says so in a note.
- An ERROR stops the offering and seeds nothing for that set; the search meets it and aborts (ADR 0036).
- Explicit `pairwise_preoracle=True` still excludes every textual conflict without asking; `False` still skips the pre-oracle.

**Cost.** Pairs the resolver does resolve are validated once up front, in addition to the supersets the search validates later.
