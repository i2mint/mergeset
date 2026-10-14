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
- A set that holds an already-known conflict (a change whose own CI is red, a declined singleton) is not offered. What is recorded for a declined offer is the change set offered, not its closure over a stack: blaming a parent for its child's conflict would hide the parent's own pairs.
- Explicit `pairwise_preoracle=True` still excludes every textual conflict without asking; `False` still skips the pre-oracle.

**Cost.** At most one resolver call per pair holds only for a resolver that declines. One that *accepts* is called once for the pair here and again inside every superset the search evaluates, because a resolution is not reused across sets: with decompose off, 3 resolvable pairs cost 6 resolver calls instead of 3 (found by the adversarial review). The resolved pairs are also validated up front. This trades paid calls on resolving resolvers for the saving on declining ones; reusing a resolution across sets removes the cost and is tracked as a follow-up.
