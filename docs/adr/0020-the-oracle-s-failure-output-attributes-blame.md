---
adr: 0020
decision: D20   # the identifier this was published under before the split
title: "The oracle's failure output attributes blame"
status: accepted
found_by: TEST workstream
---

# 0020 — The oracle's failure output attributes blame

> Found by the TEST workstream during the trial run.

`mergeset/attribution.py` mines a failure for the changes it implicates, using three signals in increasing order of strength: every path in the failure block (source frames included, not just the failing test's file); the changes that touched those paths; and — decisively — the identifiers the output names, matched against each candidate's *added* diff lines.

The third signal is not a refinement. In TEST's `{PR-04, PR-12}` case the failing test lives in a file PR-12 added, while the culprit PR-04 shares no file with it, so file-level attribution accuses the innocent change; only matching the three configuration identifiers PR-04 added against the diffs finds PR-04. In the `{PR-03, PR-06}` case four suites fail to *collect*, so there are no test ids at all — just a stack trace whose actionable frame is a source file. Both fixtures live in the local artifact store (`fixtures/` sub-store, see `docs/DECISIONS.md` D-storage) and are the tests. They are *not* committed: they are captured output from a private repository, and this repository is public.

Attribution is only ever a *hint*: it narrows the shrink, and a wrong hint costs one wasted check before falling back to unguided halving. It never decides a verdict.
