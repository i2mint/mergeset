---
adr: 0019
decision: D19   # the identifier this was published under before the split
title: "File-overlap components are a search strategy, not a soundness claim"
status: accepted
found_by: TEST workstream
---

# 0019 — File-overlap components are a search strategy, not a soundness claim

> Found by the TEST workstream during the trial run.

The original version combined per-component results and presented the combination as an answer. TEST produced the counterexample: `{PR-04, PR-12}` is a real conflict spanning two components — PR-12's drift test asserts that committed schema artifacts match TypeScript sources, and PR-04 edits those sources while touching none of PR-12's files. No evaluated subset had ever contained both, so the tool recommended a 13-change plan that fails.

Decomposition is sound for *textual* conflicts and unsound for anything a whole-repo run can see: generated artifacts, barrel exports, snapshots, type checks, project-wide lint. It is kept, because finding a conflict inside a small component is finding it cheaply — but it now only *seeds*. The components are searched first, and then a global search runs with every conflict they found already known, so it starts nearly finished. A validator may opt out by declaring `validate.component_local = True` (as `merge_only_validation` does), and the "combine freely" claim was removed from the report unless that declaration is present.
