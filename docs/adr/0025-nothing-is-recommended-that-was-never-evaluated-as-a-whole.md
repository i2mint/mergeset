---
adr: 0025
decision: D25   # the identifier this was published under before the split
title: "Nothing is recommended that was never evaluated as a whole"
status: accepted
---

# 0025 — Nothing is recommended that was never evaluated as a whole

The defect TEST found first was that a combined plan could be recommended without ever having been run: the tool splits candidates into components that share no changed file, solves each, and combines the answers. `{PR-04, PR-12}` sit in different components, so no evaluated subset ever contained both, and the emitted "merge 13 of 15" was a set the tool had never seen. It fails. File-overlap decomposition is sound for *textual* conflicts and unsound for anything a whole-repo test run can see — a drift test in one component reads generated artifacts derived from sources another component edits, with no file in common.

The guard for that is a global search seeded with every conflict the components found cheaply, so the answer is established rather than composed. That guard has been in place since v1, and `test_components_are_not_assumed_to_combine_for_a_whole_repo_validator` gates it.

**It had a hole, and the hole had the same shape as the original bug.** When the global search hit a budget (or aborted) before finding a single passing set, `analyze` fell back to the cartesian combination — which had still never been evaluated. Reproduced: two components, a whole-repo validator, `max_evaluations=1`. The tool recommended `{feat-b, feat-d}` while its own log recorded that exact set as **FAIL**, with no note saying anything was wrong. A budget is not an exotic condition; it is the normal operating mode of this tool.

Three changes, none of which relies on the search behaving well:

1. **The log has the last word.** The fallback drops any combined set the log refutes, and says which and why. Recommending a set recorded as failing is now impossible by construction, not by good behaviour upstream.
2. **When nothing combinable survives, report what was established** — `log.maximal_passing_sets()`, every one of which has a recorded PASS. Smaller than the answer, and true; that is the right trade, and it beats both "no good set was found" and a confident lie.
3. **Every plan carries `verified`**, computed from the log — an exact recorded PASS, never inference across the monotone closure. An unverified plan is labelled `NOT VERIFIED` in both reports and ranks last however cheap it looks, because a plan nobody ran is not a better answer than a smaller one somebody did. A validator that declares `component_local` is taken at its word and nothing is flagged: there, combining is sound by contract.

Rank is now assigned *after* ordering. It was assigned before, so "Plan 1" was not necessarily the first plan the reader saw — harmless while the two orders happened to agree, and actively misleading now that unverified plans are pushed to the end.

The invariant worth stating plainly, because it is what the tool is for: **every set `mergeset` recommends has been merged and validated as a whole, or is labelled as not having been.** There is no third case.
