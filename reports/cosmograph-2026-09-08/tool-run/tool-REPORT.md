# mergeset — cosmograph 2026-09-08

Base `origin/main` (`3716f38a`) · 15 candidate changes · 11 expensive evaluations spent · complete

## Recommended merge plans

### Plan 1 — merge 13 of 15

Merge in this order:

1. [`pr630`](https://github.com/cosmograph-org/cosmograph/pull/630) — Bars: public multiselect entry points + app persists the full selection (#573)
2. [`pr579`](https://github.com/cosmograph-org/cosmograph/pull/579) — Lib | Cosmograph: Hop-distance point-color strategy (shade a neighborhood by distance)
3. [`pr637`](https://github.com/cosmograph-org/cosmograph/pull/637) — Lib | Cosmograph: Describe event payloads in the params SSOT
4. [`pr632`](https://github.com/cosmograph-org/cosmograph/pull/632) — App: Save And Reset Settled Point Positions
5. [`pr616`](https://github.com/cosmograph-org/cosmograph/pull/616) — App: Capture And Restore The 3D Camera In Snapshots And Stories

That merges 5 refs and lands 13 changes: `pr575`, `pr576`, `pr587`, `pr604`, `pr631`, `pr633`, `pr634`, `pr636` come along as ancestors of the branches above.

Dropped: `pr577`, `pr602` (weight 14.56)

### Plan 2 — merge 11 of 15

Merge in this order:

1. [`pr630`](https://github.com/cosmograph-org/cosmograph/pull/630) — Bars: public multiselect entry points + app persists the full selection (#573)
2. [`pr579`](https://github.com/cosmograph-org/cosmograph/pull/579) — Lib | Cosmograph: Hop-distance point-color strategy (shade a neighborhood by distance)
3. [`pr637`](https://github.com/cosmograph-org/cosmograph/pull/637) — Lib | Cosmograph: Describe event payloads in the params SSOT
4. [`pr577`](https://github.com/cosmograph-org/cosmograph/pull/577) — App: Add graph-ops command pack (expand, reachable, path, component)
5. [`pr632`](https://github.com/cosmograph-org/cosmograph/pull/632) — App: Save And Reset Settled Point Positions

That merges 5 refs and lands 11 changes: `pr575`, `pr576`, `pr631`, `pr633`, `pr634`, `pr636` come along as ancestors of the branches above.

Dropped: `pr587`, `pr602`, `pr604`, `pr616` (weight 66.46)

## What stops the rest

**Will not merge onto the base at all** (before any test ran):

- `pr602` — `package-lock.json`, `packages/app/features/project-builder/hooks/useProjectConfigSave.tsx`, `packages/app/features/project-builder/store/CosmographProjectStore.ts`, `packages/app/next.config.js`

**Textual conflicts** (found by `git merge-tree`, before any test ran):

| a | b | files |
| --- | --- | --- |
| `pr577` | `pr616` | `tests/unit/commands.test.ts` |

**Conflicts found by validation** (merged cleanly, still failed):

- `pr602`
- `pr577`, `pr587` — failing: `test: <test failed>`

## Candidates

| change | source | head | weight | files | notes |
| --- | --- | --- | --- | --- | --- |
| `pr575` | pr | `origin/lib/graph-ops-traversal` | 30.09 | 7 | CI success |
| `pr576` | pr | `origin/lib/graph-ops-manager` | 22.17 | 13 | stacked on `pr575`; CI success |
| `pr577` | pr | `origin/app/graph-ops-commands` | 7.60 | 18 | stacked on `pr576`; CI success |
| `pr579` | pr | `origin/lib/graph-ops-hop-color` | 7.32 | 23 | stacked on `pr576`; CI success |
| `pr587` | pr | `origin/stories_refactor` | 33.91 | 67 | CI success |
| `pr602` | pr | `origin/ui/snapshot-save-dialog` | 6.96 | 66 | stacked on `pr587`; CI success |
| `pr604` | pr | `origin/stories_refactor_all_work` | 16.97 | 78 | stacked on `pr587`; CI success |
| `pr616` | pr | `origin/snapshots_w_3d` | 8.61 | 87 | stacked on `pr604`; CI success |
| `pr630` | pr | `origin/wt/multiselect-573` | 5.80 | 3 | CI success |
| `pr631` | pr | `origin/wt/ssot-377` | 36.16 | 8 | CI success |
| `pr632` | pr | `origin/wt/positions-513` | 7.64 | 9 | CI success |
| `pr633` | pr | `origin/wt/ssot-fields` | 26.68 | 8 | stacked on `pr631`; CI success |
| `pr634` | pr | `origin/wt/ssot-layer` | 19.26 | 8 | stacked on `pr633`; CI success |
| `pr636` | pr | `origin/wt/ssot-schema-version` | 12.60 | 8 | stacked on `pr634`; CI success |
| `pr637` | pr | `origin/wt/ssot-events` | 8.27 | 8 | stacked on `pr636`; CI success |

## Independent components

These groups touch no common file, so they were solved separately and their answers combine freely.

1. `pr575`, `pr576`, `pr577`, `pr579`, `pr587`, `pr602`, `pr604`, `pr616`, `pr632`
2. `pr631`, `pr633`, `pr634`, `pr636`, `pr637`
3. `pr630`

## Notes

- 10 of 15 changes are stacked on another candidate. Only downward-closed sets are considered, which reduces the search space from 32768 subsets to 1008 valid ones.
- pr637 is stacked on pr636: it already contains it, so a set holding pr637 must hold pr636, and dropping pr636 drops pr637 too.
- pr636 is stacked on pr634: it already contains it, so a set holding pr636 must hold pr634, and dropping pr634 drops pr636 too.
- pr634 is stacked on pr633: it already contains it, so a set holding pr634 must hold pr633, and dropping pr633 drops pr634 too.
- pr633 is stacked on pr631: it already contains it, so a set holding pr633 must hold pr631, and dropping pr631 drops pr633 too.
- pr616 is stacked on pr604: it already contains it, so a set holding pr616 must hold pr604, and dropping pr604 drops pr616 too.
- pr604 is stacked on pr587: it already contains it, so a set holding pr604 must hold pr587, and dropping pr587 drops pr604 too.
- pr602 is stacked on pr587: it already contains it, so a set holding pr602 must hold pr587, and dropping pr587 drops pr602 too.
- pr579 is stacked on pr576: it already contains it, so a set holding pr579 must hold pr576, and dropping pr576 drops pr579 too.
- pr577 is stacked on pr576: it already contains it, so a set holding pr577 must hold pr576, and dropping pr576 drops pr577 too.
- pr576 is stacked on pr575: it already contains it, so a set holding pr576 must hold pr575, and dropping pr575 drops pr576 too.
- pr637's CI status (`success`) is against `wt/ssot-schema-version`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr636's CI status (`success`) is against `wt/ssot-layer`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr634's CI status (`success`) is against `wt/ssot-fields`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr633's CI status (`success`) is against `wt/ssot-377`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr616's CI status (`success`) is against `stories_refactor_all_work`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr604's CI status (`success`) is against `stories_refactor`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr602's CI status (`success`) is against `stories_refactor`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr579's CI status (`success`) is against `lib/graph-ops-manager`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr577's CI status (`success`) is against `lib/graph-ops-manager`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr576's CI status (`success`) is against `lib/graph-ops-traversal`, not `origin/main`, so it is ignored as a pre-oracle. Its mergeability here is decided by actually merging it.
- pr602 does not merge onto the base at all (4 conflicting files). Excluded before any test ran.

## Evaluation log

11 rows. Every row is re-usable: a re-run costs nothing for sets already decided.

| set | verdict | stage | seconds | detail |
| --- | --- | --- | --- | --- |
| `pr575`, `pr576`, `pr579`, `pr587`, `pr604`, `pr616`, `pr632` | pass | validate | 84.9 |  |
| `pr575`, `pr576`, `pr577`, `pr579`, `pr587`, `pr604`, `pr632` | fail | validate | 28.6 | `test: <test failed>` |
| `pr575`, `pr576`, `pr577` | pass | validate | 56.4 |  |
| `pr575`, `pr576`, `pr577`, `pr579`, `pr587` | fail | validate | 25.5 | `test: <test failed>` |
| `pr575`, `pr576`, `pr577`, `pr579` | pass | validate | 50.7 |  |
| `pr575`, `pr576`, `pr577`, `pr587` | fail | validate | 28.4 | `test: <test failed>` |
| `pr575`, `pr577`, `pr587` | fail | validate | 21.2 | `test: <test failed>` |
| `pr577`, `pr587` | fail | validate | 19.2 | `test: <test failed>` |
| `pr575`, `pr576`, `pr577`, `pr579`, `pr632` | pass | validate | 39.8 |  |
| `pr631`, `pr633`, `pr634`, `pr636`, `pr637` | pass | validate | 40.8 |  |
| `pr630` | pass | validate | 39.7 |  |