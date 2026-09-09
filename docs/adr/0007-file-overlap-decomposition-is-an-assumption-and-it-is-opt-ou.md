---
adr: 0007
decision: D7   # the identifier this was published under before the split
title: "File-overlap decomposition is an assumption, and it is opt-out"
status: accepted
---

# 0007 — File-overlap decomposition is an assumption, and it is opt-out

Two changes touching disjoint file sets provably cannot conflict *textually*. They can still conflict *semantically* — change A adds a caller of a function change B deletes, in a file A never touched. The decomposition is on by default because the speedup is enormous and the failure mode is rare, and it is `decompose=False` away from being off. It is written down here rather than buried, because it is the one place where the tool can be confidently wrong.
