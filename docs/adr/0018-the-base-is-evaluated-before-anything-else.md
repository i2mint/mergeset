---
adr: 0018
decision: D18   # the identifier this was published under before the split
title: "The base is evaluated before anything else"
status: accepted
---

# 0018 — The base is evaluated before anything else

One evaluation of the empty set, on base alone. If the base does not validate, every subsequent failure is meaningless and "nothing can be merged" gets reported as a finding rather than as the misconfiguration it is. It would also have caught an earlier run where `detect_runner` classified a TypeScript repository as pytest — it checked for a `tests/` directory before looking at `package.json` — and ran pytest in it for twelve evaluations. `detect_runner` now ranks manifests above directory names, and the default validator refuses to guess rather than running the wrong command.
