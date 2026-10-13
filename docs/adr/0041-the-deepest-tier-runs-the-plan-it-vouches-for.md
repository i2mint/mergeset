---
adr: 0041
title: "The deepest tier runs the plan it vouches for, and a cheaper tier does not re-run what a deeper log refuted"
status: accepted
---

# 0041 — The deepest tier runs the plan it vouches for, and a cheaper tier does not re-run what a deeper log refuted

ADR 0030 made every cheaper tier run, not infer, a PASS on the way to a deeper one, so that `verified_tier` (ADR 0026) can name the deepest tier with an exact PASS at it and at every cheaper tier. It left the deepest tier inferring from its own log, and that is a hole (i2mint/mergeset#37): an earlier deep-only run banks a PASS for `{a, b, d}`, a screen edit (#32) or a screen that refuses `d` makes `{a, b}` maximal, and the deep tier infers `{a, b}` from the triple and never runs it. The plan is reported NOT VERIFIED although nothing is wrong with it. The mirror image wastes money: with a log written before ADR 0030, or after a screen edit, a cheaper tier ran a set a deeper log already held an exact FAIL for.

**Decision.**

1. After each confirm search, every maximal set with no exact row at that tier is run there (`_confirming_chain(..., exact_deepest=True)`), and the search is repeated. The repeat is the same `find_maximal_good_sets` call, with those sets routed to the exact chain, so a FAIL is handled exactly as any other (conflict learned, the search refines around it) and so is an ERROR (ADR 0036). It stops when every maximal set has an exact row, when asking again would change nothing, or when the tier's run or time allowance is spent; the budget is the tier's own, shared by all the repeats. A plan the budget cannot afford to run stays NOT VERIFIED, which is the honest label.
2. A cheaper tier that would have to *run* a set (it has no answer, or only an inferred PASS) first asks the deeper logs. A known FAIL there, exact or inferred, answers for the chain, and no cheap run is spent. A cheaper tier's own exact rows still answer first, so a cheap FAIL is still the reported reason.

**Rejected: make the deepest tier never infer.** That runs every interior set at the most expensive tier, which is what the chain exists to avoid. Only the sets a plan is made of need the exact row.

**Cost.** At most one extra deep run per maximal set that lacked one, none when the search had already run it.
