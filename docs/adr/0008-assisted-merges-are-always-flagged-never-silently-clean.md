---
adr: 0008
decision: D8   # the identifier this was published under before the split
title: "Assisted merges are always flagged, never silently clean"
status: accepted
---

# 0008 — Assisted merges are always flagged, never silently clean

An AI resolver may attempt a conflicted merge, under a policy that is deliberately narrow: mechanical conflicts only (both sides added imports, both appended to a changelog, adjacent independent edits, regenerable lockfiles), and an explicit refusal whenever resolving would require guessing which behaviour is correct. Any set that merged this way is recorded with `merge.assisted = True` and the resolution diff saved, and it is marked in both reports. A merge that needed a machine's judgement is a different fact from a merge that was clean, and the report must never conflate them.
