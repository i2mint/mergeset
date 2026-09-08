# Which of these branches can be merged together?

**cosmograph, 2026-09-08.** 15 open PRs by `thorwhalen`, merged onto `origin/main` @ `3716f38a`.

## The answer in one paragraph

**Twelve of the fifteen PRs merge together and pass validation as they stand: #575 #576 #587 #604 #616 #630 #631 #632 #633 #634 #636 #637.** Three are held out — #602, which does not merge onto `main` at all; #577, which breaks four test files when the stories refactor is present; and #579, which breaks the SSOT drift test. None of the three is broken on its own; each is green in isolation and each has a small, identified fix. There is no combination that keeps all fifteen.

## What was analysed

Candidates are the open PRs authored by `thorwhalen` and updated in the last 48 hours, confirmed with `gh`:

| PR | head | based on | files | size |
|---|---|---|---|---|
| #575 | `lib/graph-ops-traversal` | `main` | 7 | +1013 |
| #576 | `lib/graph-ops-manager` | #575 | 13 | +1522 |
| #577 | `app/graph-ops-commands` | #576 | 18 | +2254 −1 |
| #579 | `lib/graph-ops-hop-color` | #576 | 23 | +2035 −40 |
| #587 | `stories_refactor` | `main` | 67 | +7746 −161 |
| #602 | `ui/snapshot-save-dialog` | #587 | 66 | +7932 −162 |
| #604 | `stories_refactor_all_work` | #587 | 78 | +8730 −161 |
| #616 | `snapshots_w_3d` | #604 | 87 | +10531 −185 |
| #630 | `wt/multiselect-573` | `main` | 3 | +115 −5 |
| #631 | `wt/ssot-377` | `main` | 8 | +4757 −83 |
| #632 | `wt/positions-513` | `main` | 9 | +763 −1 |
| #633 | `wt/ssot-fields` | #631 | 8 | +5337 −83 |
| #634 | `wt/ssot-layer` | #633 | 8 | +5607 −83 |
| #636 | `wt/ssot-schema-version` | #634 | 8 | +5621 −82 |
| #637 | `wt/ssot-events` | #636 | 8 | +5606 −82 |

Two further open PRs by the same author fall outside the 48-hour window and were excluded: #603 (last touched 2026-07-22) and #584 (2026-07-24, already `CONFLICTING` on GitHub).

Nothing was rebased, no existing branch was modified, nothing was merged to `main`, nothing was pushed. All work happened in a fresh clone with its own `pnpm install`.

## What "maximal subset" means when the candidates are branches

The fifteen PRs are not fifteen independent choices. They form a **forest**:

```
graph-ops   #575 → #576 → #577              stories   #587 → #602
                        ↘ #579                              ↘ #604 → #616

SSOT        #631 → #633 → #634 → #636 → #637        solo   #630   #632
```

Three consequences shape everything below.

**A candidate set must be downward-closed.** You cannot land #616 without #604 and #587, because #616's branch *contains* them. "Only prefixes make sense" is the usual phrasing but it is not quite right here: this is a forest, not a set of chains — #577 and #579 are siblings on #576, #602 and #604 are siblings on #587. The correct statement is that a set must be closed downward under "this PR's base is that PR's head". That reduces the 2^15 = 32768 subsets to **1008 admissible sets** (6 × 6 × 7 × 4, one factor per group); once #602 is excluded as a size-1 conflict the stories factor drops from 7 to 4 and only **576** remain.

**Only the tips get merged.** Once a set is closed, merging its tip branches brings every ancestor along. The full 15-PR union is 6 branch merges, not 15.

**Dropping a change drops its cone.** Excluding #587 also excludes #602, #604 and #616 — 8700 lines. Any weighting that treats the fifteen as independent will happily make that trade to satisfy one conflict; the plans below are ranked by what actually survives.

## What one evaluation costs

Measured on `main` in a fresh clone, because this number decides how aggressive the search has to be:

| step | wall | on `main` |
|---|---|---|
| `pnpm install --frozen-lockfile` | 33 s | only needed when the lockfile changed |
| `pnpm run build:cosmos` | 9 s | **required** — without it 7 test files fail to collect |
| `pnpm run test` (vitest) | 9 s | 22 files, 276 tests, green |
| `pnpm run lint:ci` | 27 s | 0 errors, 128 warnings |

**~45 s warm, ~80 s cold**; observed 54–99 s on real merged sets. Validation here is the local equivalent of CI's *Lint* and *Unit Tests* jobs. E2E is excluded: it needs Docker, a local Supabase and a headed browser, and costs minutes rather than seconds.

## The conflicts

Four minimal conflicts, two of which no textual merge check can see.

### `{#602}` — does not merge onto `main` at all (textual, size 1)

#602 conflicts with `main` by itself, on `package-lock.json`, `packages/app/next.config.js`, `.../hooks/useProjectConfigSave.tsx` and `.../store/CosmographProjectStore.ts`. Its merge-base with `main` is `b88b1a08`: its own base branch `stories_refactor` has moved on without it.

**GitHub reports this PR as `MERGEABLE` / `CLEAN`**, because GitHub is answering "does it merge into `stories_refactor`", which is where it is targeted. Against `main` it is a size-1 conflict, and it takes itself out of every good set before any test runs.

*Fix:* merge current `stories_refactor` into `ui/snapshot-save-dialog` (or rebase it), then re-check.

### `{#577, #616}` — one hunk in a test file (textual)

`tests/unit/commands.test.ts`: #577 adds `expandNeighbors`, `expandReachable`, `getGraphComponents`, `selectComponent` and `selectPathBetween` to the sorted command-registry list; #616 rewrites the same file's mock factory and adds 3D commands. The resolution is the union of both edits — this is the conflict the earlier cross-PR gate already flagged, and it is as trivial as it looked.

It never actually binds, though: every closed set containing #616 also contains #587, so the next conflict fires first.

### `{#577, #587}` — import-time crash (semantic)

With #577 and the stories refactor both present, four test files fail to *load*: `commands.test.ts`, `graph-ops-commands.test.ts`, `snapshot-scope.test.ts`, `snapshot-story-commands.test.ts`. The cause is one line —

```
packages/app/features/project-builder/store/commands/schemas.ts:89
  z.enum(CosmographTraversalDirection)
  → TypeError: Cannot convert undefined or null to object
```

`CosmographTraversalDirection` is `undefined` at module-evaluation time. #577 introduces the schema; the stories refactor reshuffles the `packages/cosmograph/src/cosmograph/index.ts` barrel; together the symbol is not resolved when zod needs it. Verified minimal: `{#575,#576,#577}` passes, `{#587}` passes, `{#575,#576,#587}` passes, `{#575,#576,#577,#587}` fails.

*Fix:* import `CosmographTraversalDirection` from its defining module rather than through the barrel, or move the `z.enum` construction behind a lazy getter.

### `{#579, #631}` — generated artifacts go stale (semantic)

#631 adds `tests/unit/params-ssot.test.ts`, which asserts that the committed `packages/cosmograph/ai/schemas/*.json` still match the TypeScript sources. #579 adds `pointColorHopDirection`, `pointColorHopSeeds`, the `hopDistance` strategy and `TraversalDirectionType` to those sources — and its artifacts were generated before #579 existed. Merged, both schema files fail the drift test. Verified minimal: `{#575,#576,#579}` passes, `{#575,#576,#631}` passes, `{#575,#576,#579,#631}` fails.

This is the interesting shape: two PRs that are each individually correct, each CI-green, with no textual overlap at all, and their combination is wrong because one of them owns a generated artifact the other invalidates. Whoever lands second must run `pnpm run ai:params-ssot` and commit the result — and #631's own drift test is what will catch it, which is the system working as designed.

## Maximal good sets

Complements of the minimal hitting sets of the four conflicts, restricted to downward-closed sets. Each was merged and validated end to end.


### A — 12 of 15 (recommended)

**#575 #576 #587 #604 #616 #630 #631 #632 #633 #634 #636 #637** — drops #577, #579, #602.

Merged onto `origin/main` and validated clean: build ✓, 41 test files / 613 tests ✓, lint 0 errors. This is the largest good set and the one to act on. Five branch merges (the tips): `lib/graph-ops-manager`, `snapshots_w_3d`, `wt/ssot-events`, `wt/multiselect-573`, `wt/positions-513`.

Suggested landing order — independent groups first, and it matches the pitch order already planned for Nikita:

1. **#575 → #576** — graph-ops traversal primitives, then the manager API.
2. **#631 → #633 → #634 → #636 → #637** — the SSOT chain, in stack order.
3. **#587 → #604 → #616** — the stories stack, in stack order.
4. **#630**, **#632** — independent of everything above; land any time.

Merge order does not otherwise matter: every merge in this set is textually clean, so the resulting tree is the same whichever order the groups land in.

### B — 8 of 15

**#575 #576 #579 #587 #604 #616 #630 #632** — drops #577, #602 and the whole SSOT stack.

Validated clean. This is the set you get if you would rather land the hop-distance colouring (#579) than the five SSOT PRs. Strictly worse by size, and the SSOT chain is five PRs against one, so A dominates it in practice — but it is a genuinely different maximal set, not a subset of A.

### C — 10 of 15

**#575 #576 #577 #630 #631 #632 #633 #634 #636 #637** — drops #579 and the whole stories stack.

Validated clean. This is the set that keeps the graph-ops command pack (#577) at the price of the entire stories stack, because #577 and #587 cannot coexist until the barrel import is fixed.

### D — 6 of 15

**#575 #576 #577 #579 #630 #632** — drops the stories stack and the SSOT stack.

The only set that keeps both #577 and #579. Smallest of the four; listed for completeness because it is maximal, not because it is attractive.

## Recommended plan

Land **set A** (12 PRs). Then bring the other three back one at a time, each with a one-line fix:

| held out | why | what unblocks it |
|---|---|---|
| **#602** | does not merge onto `main`; base branch moved on | merge current `stories_refactor` into `ui/snapshot-save-dialog` — this is stale-branch maintenance, not a design problem |
| **#577** | `z.enum(CosmographTraversalDirection)` sees `undefined` once the stories refactor lands | import the enum from its defining module instead of through the `cosmograph` barrel (or make the schema lazy). Also re-do the one-hunk `commands.test.ts` merge against #616 |
| **#579** | invalidates the generated `ai/schemas/*.json` that #631's drift test guards | `pnpm run ai:params-ssot` and commit the regenerated artifacts |

None of these is a reason to hold a PR. All three are green on their own; they are *interaction* costs, and the two semantic ones only become visible when the sets are actually built and tested — which is the point of the exercise.

Two of the three land-order facts are worth stating explicitly, because they are not visible from any single PR page:

- **#577 must land after #587, not before**, and needs the barrel fix at that moment. Landing #577 first and #587 second produces the same broken tree, just later.
- **#579 and #631 are order-independent but not fix-independent**: whichever lands second must regenerate the artifacts. #631's drift test is precisely what makes that unmissable, so the ordering is safe as long as CI runs on the second one after the first has landed.

## Integration branches

One local branch per maximal good set, each pointing at exactly the merge commit that was validated:

- `integration/2026-09-08-a` — set A (12 PRs)
- `integration/2026-09-08-b` — set B (8 PRs)
- `integration/2026-09-08-c` — set C (10 PRs)
- `integration/2026-09-08-d` — set D (6 PRs)

They live in the analysis clone (`_worktrees/c-mergeset-test/repo`) and are **local only** — nothing was pushed. To look at one: `git -C <clone> checkout integration/2026-09-08-a`.

## How this was computed

The loop is the one in the spec (MARCO / hitting-set-tree), run by hand:

1. Evaluate the full union → merge conflict at #602.
2. Shrink → `{#602}` is a size-1 conflict. Drop it, re-evaluate → merge conflict at #616 against #577.
3. Hitting sets of `{{#602}, {#577,#616}}` give two candidates; both **fail on tests**, revealing two conflicts no textual check could find.
4. The *identities of the failing tests* — not blind halving — pointed straight at the responsible pair in both cases: a drift test that names its artifacts, and a stack trace that names the symbol and the file. Two targeted evaluations confirmed each; three more confirmed minimality.
5. Hitting sets of all four conflicts, restricted to downward-closed sets, give the four maximal sets above. Each was evaluated end to end.

**16 evaluations, 640 s (10.7 min) of machine time.** Everything is in `evaluations.jsonl`, which is the source of truth for the run; the report, the HTML and the integration branches are all derived from it and can be regenerated without re-running anything.

## Method notes worth keeping

**`git merge-tree A B` is the wrong pre-oracle.** It merges at `merge-base(A, B)`, which is not the base you are landing on when one branch is stale. Run that way, this PR set reports **13 conflicting pairs**; 11 are pure artefacts of #602's staleness, because `main`'s own commits show up as conflicts. Chaining instead — `merge-tree` the accumulated commit with the next branch, `commit-tree` the result, feed it back — merges sequentially onto the real base, entirely in the object database with no worktree, and yields the 2 real conflicts.

**`gh`'s `mergeable` / `mergeStateStatus` only answers the question the PR asks.** #602 is `MERGEABLE` / `CLEAN` on GitHub and a size-1 conflict against `main`. The flag is usable as a pre-oracle only when the PR's `baseRefName` is the base under analysis.

**The build step is a prerequisite of the oracle, not part of it.** Without `pnpm run build:cosmos`, 7 test files fail to collect on plain `main` — a validator that runs the test command alone reports a false failure on every set.

**A pass/fail bit is not enough.** Both semantic conflicts here were localised by reading which tests failed and why. Halving would have worked, at several times the cost.

**Monotonicity held.** No set that passed had a failing subset, and no set that failed had a passing superset, across all 16 evaluations. Flakiness was not directly tested — no set was evaluated twice — so that consistency is the only evidence, but it is the evidence the search relies on and nothing contradicted it.

## Cross-check: the same analysis through the `mergeset` tool

The parallel workstream's package was run over the identical 15 PRs, base and validation (`reports/cosmograph-2026-09-08/tool-run/`). It agreed on the cheap findings and disagreed on the answer.

It got right, and got there more cleanly than the manual run: #602 excluded before any test; `{#577, #616}` found textually; `{#577, #587}` found by validation and **shrunk to exactly that pair** without needing a hypothesis, which is the part a solver should beat a human at.

It got the recommendation wrong. Its Plan 1 is "merge 13 of 15, dropping only #577 and #602" — a set already in this run's log as a failure, on the `params-ssot` drift test. The reason is instructive rather than embarrassing: the tool splits candidates into components that share no changed file, solves each separately, and combines the answers. #579 and #631 land in different components, so **no subset it evaluated contained both**, their conflict was never tested, and the combined plan was emitted without ever being run as a whole.

The lesson generalises past this repo: **decomposition by changed-file overlap is sound for textual conflicts and unsound for anything a whole-repo test run can see** — generated artifacts, barrel exports, snapshot tests, type checking, project-wide lint. The cheap fix is to treat a combined plan as a *candidate* and evaluate it once before recommending it. Both findings are written up for the tool in `HANDOFF.md`.

## Files

- `REPORT.md` — this file
- `report.html` — self-contained visual (conflict graph, minimal conflicts, maximal sets, evaluation log)
- `evaluations.jsonl` — every evaluation, in order; the source of truth
- `preoracle.json` / `seqmerge.json` — the git-only pre-oracle results
- `conflicts.json` — the derived conflict set and maximal good sets
- `preoracle.py`, `seqmerge.py`, `mss_driver.py`, `evaluate.sh`, `mkhtml.py`, `mkbranches.py` — the ad-hoc scripts that produced all of it
- `logs/` — full build/test/lint output for every evaluation
- `tool-run/` — the same analysis re-run through the `mergeset` package, with its report, HTML and evaluation log
- `REPORT-1-adhoc.md` — the earlier interim report, kept for the record
