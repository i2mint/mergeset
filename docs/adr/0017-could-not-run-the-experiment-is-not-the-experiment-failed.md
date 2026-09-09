---
adr: 0017
decision: D17   # the identifier this was published under before the split
title: "'Could not run the experiment' is not 'the experiment failed'"
status: accepted
found_by: TEST workstream
---

# 0017 — "Could not run the experiment" is not "the experiment failed"

> Found by the TEST workstream during the trial run.

TEST passed a bad `reuse_worktree` and got a confident report: *Plan 1 — merge 0 of 15 · 24 expensive evaluations spent · complete*. Every checkout error had been recorded as a textual merge conflict. Three changes:

- `MergeOutcome.reason` is `'conflict'` or `'error'`, and only a conflict may enter the conflict set.
- An error produces `Verdict.ERROR`, and the search **aborts** on the first one. Continuing past an untestable evaluation manufactures conflicts out of infrastructure problems.
- `reuse_worktree` is validated (absolute path, real worktree) with an error message naming the fix — the original failure was passing `True` to an `Optional[str]`.

The tell in the bad reports was that `conflicting_files` was empty; a real textual conflict always names files.
