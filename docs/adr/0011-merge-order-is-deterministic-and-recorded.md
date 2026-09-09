---
adr: 0011
decision: D11   # the identifier this was published under before the split
title: "Merge order is deterministic and recorded"
status: accepted
---

# 0011 — Merge order is deterministic and recorded

Order should not matter when merges are clean. When it does matter, the run must still be reproducible, so `merge_order` sorts stacked changes parent-first and otherwise smallest-first (which surfaces cheap conflicts early), and the order used is stored on every log row.
