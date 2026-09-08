# cosmograph merge-set analysis — first report (ad hoc, pre-tool)

Session `c-mergeset-test`, 2026-09-08. Produced with hand-written scripts (`preoracle.py`, `seqmerge.py`, `mss_driver.py`, `evaluate.sh` in this directory) before the `mergeset` package existed. Superseded by `REPORT.md` once the analysis was re-run with the tool.

## Scope

Repository `cosmograph-org/cosmograph`. Candidates: the 15 open PRs authored by `thorwhalen` and updated in the last 48 hours — **#575 #576 #577 #579 #587 #602 #604 #616 #630 #631 #632 #633 #634 #636 #637**. Two further open PRs by the same author fall outside the window and are excluded: #603 (last touched 2026-07-22) and #584 (2026-07-24, already `CONFLICTING` on GitHub).

Base: `origin/main` at `3716f38a`. Nothing was rebased, no existing branch was touched, nothing was merged to `main`. Work happened in a fresh clone under `_worktrees/c-mergeset-test/repo` with its own `pnpm install`.

## How much does one evaluation cost?

This is the number that sets the whole budget, so it was measured first, on `main`:

| step | wall | result on `main` |
|---|---|---|
| `pnpm install --frozen-lockfile` | 33 s | — |
| `pnpm run build:cosmos` | 9 s | required; without it 7 test files fail to collect and vitest reports 7 failed files / 146 passed tests |
| `pnpm run test` (vitest) | 9 s | 22 files, 276 tests, all green |
| `pnpm run lint:ci` | 27 s | 0 errors, 128 warnings |

**~45 s warm, ~80 s cold** for the local equivalent of the CI `Lint` + `Unit Tests` jobs. Observed evaluations of full 13-PR merges ran 54–99 s. E2E (`playwright`) is excluded: it needs Docker, a local Supabase and a headed browser, and is minutes rather than seconds.

The practical consequence is that on this repo the interesting economy is **not** fail-fast or test-impact selection — it is not reinstalling dependencies, and not rebuilding `@cosmograph/cosmos` when nothing under `packages/cosmos` changed.

## The candidate set is a forest, not a flat set

The 15 PRs form four groups:

```
graph-ops   #575 → #576 → #577              stories   #587 → #602
                        ↘ #579                              ↘ #604 → #616

SSOT        #631 → #633 → #634 → #636 → #637        solo   #630   #632
```

A set of PRs is only meaningful if it is **downward-closed** under the "PR's base is another PR's head" relation — you cannot land #616 without #604 and #587. Note this is a *forest*, not a set of chains: #577/#579 are siblings on #576, and #602/#604 are siblings on #587. Once a set is closed, only its **tips** need merging; the ancestors come along in the merge. That reduces the 15-element full union to 6 branch merges, and reduces the search space from 2^15 = 32768 subsets to **576 downward-closed sets**.

## Cheap pre-oracles, before any test ran

**Singleton merge onto base.** 14 of 15 merge cleanly onto `origin/main`. **#602 does not** — it conflicts on `package-lock.json`, `packages/app/next.config.js`, `packages/app/features/project-builder/hooks/useProjectConfigSave.tsx` and `packages/app/features/project-builder/store/CosmographProjectStore.ts`. Its merge-base with `main` is `b88b1a08`, i.e. its own base branch `stories_refactor` has moved on without it.

This is worth dwelling on, because **GitHub reports #602 as `MERGEABLE` / `CLEAN`**. GitHub is answering a different question: mergeable *into `stories_refactor`*, which is where the PR is targeted. Against `main` it is a size-1 conflict. A PR's `mergeable` flag is only usable as a pre-oracle when its `baseRefName` is the base you actually intend to merge onto.

`{#602}` is therefore a minimal conflict of size 1, and it is excluded from every good set for free.

**Pairwise textual merge.** One real conflict: **`{#577, #616}`**, a single hunk in `tests/unit/commands.test.ts` (both add command ids to the same list; keeping both is the obvious resolution). This matches the cross-PR gate run earlier in the day.

A methodological warning that cost us the first sweep: the naive `git merge-tree A B` uses `merge-base(A, B)`, which is the wrong base whenever one branch is stale. Run that way, this PR set reports **13 conflicting pairs** — 11 of them purely artefacts of #602's staleness, since `main`'s own commits show up as conflicts. Merging sequentially onto the base instead (chain `merge-tree` → `commit-tree` → feed back in, entirely in the object database, no worktree) reduces that to the 2 real conflicts above.

**File overlap.** The overlap graph does not decompose into independent components: `packages/cosmograph/src/cosmograph/index.ts` is touched by the graph-ops stack, the stories stack and #577, and `packages/app/features/project-builder/view-config-panel/point-panels/PointPositionsPanel.tsx` links #632 to the stories stack. So there is one component, not four; the decomposition optimisation buys nothing here.

## Evaluations run so far

Every evaluation is appended to `evaluations.jsonl` (the source of truth for this run).

| set | verdict | why |
|---|---|---|
| all 15 | merge conflict | #602 vs base |
| all 15 − #602 | merge conflict | #577 vs #616, `tests/unit/commands.test.ts` |
| all 15 − {#602, #577} | **tests fail** | 2 failures, 620 passed (99 s) |
| all 15 − {#602, #616} | **tests fail** | 2 failures + 4 files failed to collect, 506 passed (54 s) |

So the two hitting sets of the known textual conflicts are both bad, and there are at least two further conflicts that no amount of textual merge checking would have found:

**Semantic conflict 1 — `{#579, SSOT stack}` (drift test).** `tests/unit/params-ssot.test.ts`, added by #631, asserts that the committed `packages/cosmograph/ai/schemas/*.json` match the TypeScript sources. #579 adds new config params (`pointColorHopDirection`, `pointColorHopSeeds`, the `hopDistance` strategy, `TraversalDirectionType`) to the TS sources without regenerating those artifacts — they were generated before #579 existed. Merged together, the drift test fails on both schema files. This is a *generated-artifact* conflict: each PR is individually correct and CI-green, and the fix is mechanical (`pnpm run ai:params-ssot` after the merge), but no textual merge check can see it.

**Semantic conflict 2 — `{#577, stories stack}` (import-time crash).** With #577 present and #616 dropped, four test files fail to even load: `packages/app/features/project-builder/store/commands/schemas.ts:89` calls `z.enum(CosmographTraversalDirection)` and `CosmographTraversalDirection` is `undefined` at that point, so zod throws `TypeError: Cannot convert undefined or null to object`. #577 introduces the schema, the stories refactor reshuffles the `packages/cosmograph/src/cosmograph/index.ts` barrel; together the symbol is not resolved at module-evaluation time. Both PRs are green alone.

Notice what this does to the "one bit per evaluation" assumption: the *failing test identities* are what pointed straight at the responsible pair, in both cases. Blind halving would have needed several more runs.

## Where this stands

Two textual conflicts (`{#602}`, `{#577,#616}`) and at least two semantic ones are known. Minimisation of the semantic conflicts and the enumeration of the actual maximal good sets is in progress; the recommended landing plan is in `REPORT.md`.

## Facts to carry forward

- `pnpm run build:cosmos` is a **prerequisite of the oracle**, not part of it. A validator that runs the test command alone reports a false failure on this repo.
- The correct pairwise pre-oracle merges onto the *base*, not branch-against-branch.
- `gh`'s `mergeable` / `mergeStateStatus` is only meaningful when the PR's base equals the base under analysis.
- Dropping a stack root drops its whole descendant cone; weights in the hitting set must account for that or the solver will cheerfully discard thousands of lines to satisfy one conflict.
