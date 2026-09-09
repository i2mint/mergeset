---
adr: 0005
decision: D5   # the identifier this was published under before the split
title: "Monotonicity is a prior, not an invariant, and violations are reported rather than smoothed over"
status: accepted
---

# 0005 — Monotonicity is a prior, not an invariant, and violations are reported rather than smoothed over

The theory says good sets are downward-closed. Reality disagrees in two ways: a change can contain the *fix* that makes another change work (so a superset of a bad set passes), and flaky tests break closure outright. `EvaluationLog.monotonicity_violations()` detects the contradiction and `analyze` surfaces it as a loud note on the report instead of silently trusting a wrong inference. `flake_tolerant(validate, retries=n)` is the cheap mitigation; the honest answer is telling the user their result is not trustworthy.
