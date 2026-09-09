---
adr: 0024
decision: D24   # the identifier this was published under before the split
title: "Nothing is reported twice under two explanations"
status: accepted
found_by: TEST workstream
---

# 0024 — Nothing is reported twice under two explanations

> Found by the TEST workstream during the trial run.

A change that will not merge onto the base at all was listed under "will not merge", and then again under "conflicts found by validation" — where it had no business, since nothing was ever run on it. The second section now excludes any conflict already explained by a textual clash or a singleton merge failure. In the same spirit, the `evaluated` progress event carries `cached`, so a caller can tell a free cache hit from a real, minutes-long run; the CLI's progress output no longer prints them, which had made the shrink look as if it were re-running the same set repeatedly.
