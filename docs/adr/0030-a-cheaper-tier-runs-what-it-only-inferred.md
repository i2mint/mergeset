---
adr: 0030
title: "On the way to a deeper tier, a cheaper tier runs what it had only inferred"
status: accepted
---

# 0030 — On the way to a deeper tier, a cheaper tier runs what it had only inferred

`TieredAnalysis.verified_tier` (ADR 0026) names the deepest tier with an exact recorded PASS at it and at every cheaper tier; inference does not count, per D25. The confirm stages chain the tiers, each cached by its own log, and the cache answered a cheaper tier from the monotone closure. So the screen passed `{a, b}` on inference from a passing `{a, b, d}`, the deep tier refuted the triple and passed `{a, b}` exactly, and the plan, run at the deep tier, was reported NOT VERIFIED with "nothing validated yet" (i2mint/mergeset#31).

**Rejected: let a cheaper tier's inferred PASS count in `verified_tier`.** It was the first fix tried, and its adversarial review broke it: when a change fixes another, `{a, b, d}` passes the screen while `{a, b}` fails it. The screen never ran `{a, b}`, so no monotonicity violation could surface, and the report called a set the screen fails "confirmed at the deepest tier" and "provably maximal".

**Decision.** In the confirm chain (`_confirming_chain`), every tier but the deepest answers from its log only with an exact row or an inferred FAIL. A PASS it would only infer is run for real and recorded (`EvaluationLog.caching(infer_pass=False)`). The deepest tier in the chain still infers from its own results, as any search does. `verified_tier` keeps its strict rule.

**Cost.** At most one cheap run per deep run, which is cheap by the tiers' own ordering, and a cheap FAIL saves the deep run outright. Monotonicity violations that these runs expose are reported per tier (`MONOTONICITY VIOLATION at tier ...`), beside the ones `analyze` reports for the screen search.
