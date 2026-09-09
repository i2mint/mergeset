---
adr: 0013
decision: D13   # the identifier this was published under before the split
title: "`git merge-tree` is always chained through base"
status: accepted
found_by: TEST workstream
---

# 0013 — `git merge-tree` is always chained through base

> Found by the TEST workstream during the trial run.

`git merge-tree A B` merges at `merge-base(A, B)`. When two candidates were cut at different times — one is stale — that merge base is older than the base we actually care about, and the base branch's own commits are reported as conflicts. Measured by the TEST workstream on a real 15-PR set: the naive pairwise sweep found **13 conflicting pairs where only 2 were real**, eleven false positives from a single stale branch.

Every git operation now goes through `gitops.merge_sequence`, which merges onto base one change at a time in the object database (`merge-tree --write-tree acc head` → `commit-tree`). A pleasant consequence: a conflicted set costs milliseconds and never touches the filesystem, and a clean set yields a real commit, so the worktree step becomes a checkout rather than a sequence of merges.
