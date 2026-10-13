---
adr: 0039
title: "A tier that aborts has not been reached"
status: accepted
---

# 0039 — A tier that aborts has not been reached

`analyze_tiered` recorded `depth_reached = <tier>` before it looked at whether that tier's search had aborted, so a tier that met an `ERROR` was at once "reached" and "did not run because it aborted", and its partial maximal sets replaced the previous depth's answer under a depth they had not earned (i2mint/mergeset#55, found by the review of #52).

**Decision.** A confirm tier whose search aborts confirmed nothing. The depth stays at the last tier that finished, the aborted search's partial sets are not applied (its conflicts are kept: they are evidence), the anytime answer is refreshed at the old depth, and the notes say the tier "ran but it aborted". Every set is therefore flagged `NOT VERIFIED` at the depth that is actually claimed, which is what ADR 0038's tier-aware report then describes.
