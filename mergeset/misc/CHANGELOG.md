# Changelog

## 2026-09-08 — first version

Built in one session alongside a TEST workstream running the tool on a live 15-PR repository, which is why several of the entries below read as corrections: they are.

**Core.** MARCO-shaped search (`solve.py`): QuickXplain conflict minimization, weight-ordered Reiter hitting-set enumeration, budgets that always return labelled-partial results. Append-only JSONL evaluation log as the single source of truth, with lazy monotone closure and violation detection (`log.py`). Git pre-oracles and object-database merging (`gitops.py`). Change sources for branches, commits and GitHub PRs (`sources.py`). Pytest, command, `act`, callable, merge-only and staged validators (`validation.py`). Markdown and self-contained HTML reports (`report.py`). `cw` CLI over an SSOT function list (`cli.py`).

**Corrections made before the first release, each from a real failure:**

- `git merge-tree` is chained through base, not run pairwise — pairwise reported 13 conflicting pairs where 2 were real.
- An unrunnable evaluation is `Verdict.ERROR` and aborts the search, instead of being recorded as a conflict; the previous behaviour reported "merge 0 of 15 · complete" for a bad worktree path.
- The base is evaluated on its own first; a base that does not validate is a refusal.
- File-overlap components seed the search rather than deciding it, because a whole-repo validator can fail on changes sharing no file.
- Stacked changes are handled as a forest (`stacks.py`): downward-closed sets, tips-only merging, cone weights — and shrinking stays inside the closure.
- Failure output is mined for the changes it implicates (`attribution.py`), including symbol matching against diffs, which is the only signal that attributes a failure to a change sharing no file with the failing test.
- `detect_runner` ranks manifests above directory names; it previously called a TypeScript repository pytest.
- An empty `EvaluationLog` is no longer falsy, so `log or EvaluationLog(...)` stops discarding a caller's log.

**Shipped alongside:** a Claude Code subagent (`.claude/agents/mergeset-analyst.md`) and skill (`skills/mergeset/`), `DECISIONS.md` (21 decisions), `RESEARCH.md` (the MUS/MSS and merge-queue literature, and what was deliberately not depended on).
