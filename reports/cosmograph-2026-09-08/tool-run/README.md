# The same analysis, re-run through the `mergeset` package

`toolrun.py` drives `mergeset` over the identical 15 PRs, base and validation as the ad-hoc run in the parent directory, so the two answers can be diffed. It was run twice.

## Second run (`tool-REPORT.md`, `tool-report.html`, `evaluations.jsonl`) — agrees

21 evaluations, 954 s. Same four minimal conflicts and the same four maximal good sets as `../REPORT.md`, in the same order by size: Plan 1 = set A (12 PRs), Plan 2 = C (10), Plan 3 = B (8), Plan 4 = D (6). It derived both semantic conflicts without being given a hypothesis, which the manual run needed. Its merge plans are more directly usable than the manual report's: they name the tip refs to merge and say which changes ride along as ancestors.

## First run (`tool-REPORT-before-fixes.md`, `evaluations-before-fixes.jsonl`) — kept as the counterexample

The earlier version recommended "merge 13 of 15", dropping only #577 and #602. That set fails, on `tests/unit/params-ssot.test.ts` — it is byte-identical to a failing row in the parent `evaluations.jsonl`. The cause was its file-overlap decomposition: **no** subset it evaluated contained both #579 and #631, because they share no changed file, so their conflict was never tested and the component answers were combined into a plan that had not been run as a whole. The second run's log has five such subsets.

The general lesson, which outlives this repo: decomposition by changed-file overlap is sound for *textual* conflicts and unsound for anything a whole-repo test run can see — generated artifacts, barrel exports, snapshot tests, type checking, project-wide lint.

Both runs and the fixes between them are written up as TEST entries in `../../../HANDOFF.md`.
