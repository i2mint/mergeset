---
adr: 0004
decision: D4   # the identifier this was published under before the split
title: "The evaluation log is the single source of truth, and it is append-only JSONL"
status: accepted
---

# 0004 — The evaluation log is the single source of truth, and it is append-only JSONL

`~/.local/share/mergeset/evaluations/<repo>.jsonl` (see D-storage), one JSON object per evaluated set. Everything else — the conflict set, the known-good/known-bad closure, the merge plan, both reports — is *derived* and re-derivable, so a report can be regenerated without re-running anything and a crashed run resumes for free.

Two consequences worth naming:

- The monotone closure is computed lazily from the rows, never materialized. Materializing it would mean writing `2**|S|` implied facts for every passing set.
- The persistence seam is one keyword (`store`): anything with `append(jdict)` and `__iter__` works, so an in-memory log (tests), a `dol` store, or a database table are all drop-ins. The default is a plain file because the default must work with no dependency at all.
