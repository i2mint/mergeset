---
adr: 0031
title: "An assisted resolution is made once, vouched for, and kept"
status: accepted
---

# 0031 — An assisted resolution is made once, vouched for, and kept

Since #28 every tier merged sets the way the screen did, resolver included, so with `--resolver claude` each tier asked for a fresh resolution of every conflicting set: paid calls multiplied by the number of tiers, and a deep tier could validate a different resolved tree than the one the screen passed (i2mint/mergeset#30).

**Decision: only the first tier resolves.** The resolver's merge commit is recorded on the row (`MergeOutcome.resolved_commit`, stored as `merge_resolved_commit` beside `merge` so older releases still read the log). Deeper tiers are built with `git_oracle(resolution=...)` instead of `resolver=`: on a conflict they check out the screen's recorded commit for the set, once it is shown to exist and to hold the base and every head, and refuse the set (`ERROR`) when there is none to reuse. They never resolve again. The recorded diff is not replayed: it is a truncated `git show` of a merge commit, and the commit itself is exact.

**A resolution is vouched for before it is recorded.** The resolver path merges every head in order and offers each conflict in turn (it used to stop at the first conflict, so later heads were never in the tree the row vouched for). After each resolver call the commit must hold the base and every head merged so far, the merge must be finished with no tracked change left outside the commit, and the commit may differ from git's own merge of that head (`git merge-tree --write-tree`) only in the files that conflicted. Otherwise the resolver declined, whatever it returned: taking one side wholesale and `merge -s ours` both fail these checks. Untracked and ignored leftovers (a `__pycache__`, a regenerated file) are removed rather than declined, so the tree the screen validates is exactly the recorded commit. A resolver that raises (a timeout) has declined too: the set is a textual conflict, not an `ERROR` that would abort the search over one slow call.

**The commit is kept reachable** under `refs/mergeset/resolved/<sha>`, or `git gc` prunes it once the worktree is gone and every later deep run refuses the set. This widens ADR 0012 ("only new local branches are ever created"): mergeset also creates hidden refs in that one namespace. They are never branches, never overwrite an existing ref, do not appear in `git branch`, and are not pushed by an ordinary `git push` (a `push --mirror` would publish them). To remove them: `git for-each-ref --format='%(refname)' refs/mergeset/resolved/ | xargs -r -n1 git update-ref -d`; a log whose resolutions were removed then refuses those sets at the deep tiers until it is re-run fresh.

**Upgrade.** Assisted PASS rows written before this record no commit. A deep tier refuses those sets with "no assisted resolution of it was recorded to reuse … re-run the first tier with a fresh log".
