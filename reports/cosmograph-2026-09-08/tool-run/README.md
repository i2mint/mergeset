# The same analysis, re-run through the `mergeset` package

`toolrun.py` drives `mergeset` over the identical 15 PRs, base and validation as the ad-hoc run in the parent directory, so the two answers can be diffed. `tool-REPORT.md` / `tool-report.html` are the tool's own output; `evaluations.jsonl` is its evaluation log (11 rows).

**The tool's Plan 1 does not work.** It recommends 13 of 15 (dropping only #577 and #602); that exact set is a FAIL in the parent `evaluations.jsonl`, on `tests/unit/params-ssot.test.ts`. The cause is its file-overlap decomposition: no evaluated subset contains both #579 and #631, because they share no changed file, so their conflict was never tested and the component answers were combined into a plan that had not been evaluated as a whole. The correct answer remains the 12-PR set A in `../REPORT.md`.

What the tool got right and the manual run did not do as well: it excluded #602 before any test, found `{#577,#616}` textually, and found `{#577,#587}` by validation and shrank to exactly that pair without needing a hypothesis.

Both findings are written up as TEST entries in `../../../HANDOFF.md`.
