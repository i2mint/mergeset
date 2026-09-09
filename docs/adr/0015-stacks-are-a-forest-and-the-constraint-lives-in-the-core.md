---
adr: 0015
decision: D15   # the identifier this was published under before the split
title: "Stacks are a forest, and the constraint lives in the core"
status: accepted
found_by: TEST workstream
---

# 0015 — Stacks are a forest, and the constraint lives in the core

> Found by the TEST workstream during the trial run.

TEST's framing, adopted verbatim: **a valid candidate set is downward-closed under the parent relation**. Not "a prefix of a chain" — stacks branch, so siblings share a parent. Four consequences, all in `mergeset/stacks.py`: close a set before evaluating it; drop a change's whole descendant cone when dropping it; merge only the *tips*, since a tip brings its ancestors (15 changes became 6 merges); and weight a change by its cone, or the hitting set will drop a stack root believing it dropped one small PR. On the observed forest this cut the search space from 32768 subsets to 576.

Shrinking must respect the closure too. QuickXplain proposes arbitrary subsets, and an arbitrary subset of a stack is a fiction: `{577, 587}` and `{575, 577, 587}` and `{575, 576, 577, 587}` all produce the same merged tree, so TEST's log recorded two duplicate evaluations under different labels. The solver now closes every subset before evaluating it, which both makes the log honest and collapses those onto one cache entry.
