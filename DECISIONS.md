# Decisions

Every non-obvious choice, with the reason. Entries are append-only; when a decision is reversed, the old entry stays and the new one says what changed.

## D1 — The name is `mergeset`

Free on PyPI (404), `github.com/i2mint/mergeset` did not exist, and `import mergeset` shadows nothing in the stdlib or in any well-known package. It also names the exact object the tool computes: the maximal *merge sets*. Runners-up, all also free: `greenset`, `braidy`, `knitset`, `amalgo`, `lattix`, `maxmerge`. Rejected because taken on PyPI: `confluo`, `conflux`, `medley`, `plexus`.

## D2 — The unit is a **change**, not a branch or a PR

A change is a commit range `base..head`. Branches, pull requests and explicit commit lists are *sources* that produce changes; a PR source additionally carries metadata (number, author, title, CI status, base ref, draft flag, stack relationship) in `Change.meta`.

The reason to pick one word and hold it: the same analysis has to serve "these five local branches", "these PRs updated in the last 48h", and "these cherry-picks", and if the vocabulary tracks the source then every function ends up with three names for one idea. Only the *sources* module knows the word "PR"; the solver, the log and the report never say it. Metadata rides along for weighting and reporting but the solver never reads it — that keeps the search honest and testable without a repository.

## D3 — The CLI adapter is `cw`, not `argh`

The spec asked for `argh`. `argh` is LGPL-3.0-or-later and is being removed fleet-wide (per the `python-dispatching` skill), so this package uses `cw`, which is MIT with zero runtime dependencies. The durable part is `mergeset/cli.py::_dispatch_funcs` — an SSOT list of plain functions — and only the last line binds it to an adapter, so this decision costs one line to reverse and the same list is what a future HTTP or MCP surface would consume.

## D4 — The evaluation log is the single source of truth, and it is append-only JSONL

`~/.local/share/mergeset/evaluations/<repo>.jsonl` (see D-storage), one JSON object per evaluated set. Everything else — the conflict set, the known-good/known-bad closure, the merge plan, both reports — is *derived* and re-derivable, so a report can be regenerated without re-running anything and a crashed run resumes for free.

Two consequences worth naming:

- The monotone closure is computed lazily from the rows, never materialized. Materializing it would mean writing `2**|S|` implied facts for every passing set.
- The persistence seam is one keyword (`store`): anything with `append(jdict)` and `__iter__` works, so an in-memory log (tests), a `dol` store, or a database table are all drop-ins. The default is a plain file because the default must work with no dependency at all.

## D5 — Monotonicity is a prior, not an invariant, and violations are reported rather than smoothed over

The theory says good sets are downward-closed. Reality disagrees in two ways: a change can contain the *fix* that makes another change work (so a superset of a bad set passes), and flaky tests break closure outright. `EvaluationLog.monotonicity_violations()` detects the contradiction and `analyze` surfaces it as a loud note on the report instead of silently trusting a wrong inference. `flake_tolerant(validate, retries=n)` is the cheap mitigation; the honest answer is telling the user their result is not trustworthy.

## D6 — Cost ordering is the architecture

The pipeline is ordered by price, and nothing expensive runs until everything cheap has had its say:

1. **free** — a change whose own CI is already red against its base is a conflict of size one;
2. **milliseconds** — pairwise `git merge-tree --write-tree` finds textual conflicts with no worktree and no checkout (this is why git >= 2.38 is a hard requirement, checked up front with a fixable error message);
3. **milliseconds** — file-overlap connected components split one `2**n` search into several small independent ones, whose answers combine by Cartesian product;
4. **minutes each** — only then the real merge-and-test oracle.

Each of 1–3 can be switched off by one keyword, because each embeds an assumption (see D7) that may not hold for a given repository.

## D7 — File-overlap decomposition is an assumption, and it is opt-out

Two changes touching disjoint file sets provably cannot conflict *textually*. They can still conflict *semantically* — change A adds a caller of a function change B deletes, in a file A never touched. The decomposition is on by default because the speedup is enormous and the failure mode is rare, and it is `decompose=False` away from being off. It is written down here rather than buried, because it is the one place where the tool can be confidently wrong.

## D8 — Assisted merges are always flagged, never silently clean

An AI resolver may attempt a conflicted merge, under a policy that is deliberately narrow: mechanical conflicts only (both sides added imports, both appended to a changelog, adjacent independent edits, regenerable lockfiles), and an explicit refusal whenever resolving would require guessing which behaviour is correct. Any set that merged this way is recorded with `merge.assisted = True` and the resolution diff saved, and it is marked in both reports. A merge that needed a machine's judgement is a different fact from a merge that was clean, and the report must never conflate them.

## D9 — Weights mean "cost of dropping this change"

The hitting set is weighted so that when something must be dropped, the tool drops the *cheapest* work. Default weight is `1 + log1p(lines changed)`: bigger changes are worth more, log-shaped so one huge branch cannot dominate. Overridable with any `Change -> float`, and PR metadata (labels, author, age) is right there in `change.meta` for a policy that wants it.

## D10 — The oracle returns a record, not a bit

Every evaluation returns which tests failed, which files they live in, the merge order used, the conflicting paths and the duration. The solver uses the merge outcome's attribution to aim `quickxplain` at the changes actually implicated instead of halving blindly, and the report can say *why* two changes conflict rather than only *that* they do. Returning a bit would have been simpler and would have thrown away the most useful thing an expensive run produces.

## D11 — Merge order is deterministic and recorded

Order should not matter when merges are clean. When it does matter, the run must still be reproducible, so `merge_order` sorts stacked changes parent-first and otherwise smallest-first (which surfaces cheap conflicts early), and the order used is stored on every log row.

## D12 — Only *new* local branches are ever created

`create_integration_branch` refuses to touch a branch that already exists unless explicitly forced, and nothing in the package pushes. This is a hard safety boundary, not a default: the tool is pointed at repositories where existing branches are other people's in-flight work.


## D13 — `git merge-tree` is always chained through base (found by TEST)

`git merge-tree A B` merges at `merge-base(A, B)`. When two candidates were cut at different times — one is stale — that merge base is older than the base we actually care about, and the base branch's own commits are reported as conflicts. Measured by the TEST workstream on a real 15-PR set: the naive pairwise sweep found **13 conflicting pairs where only 2 were real**, eleven false positives from a single stale branch.

Every git operation now goes through `gitops.merge_sequence`, which merges onto base one change at a time in the object database (`merge-tree --write-tree acc head` → `commit-tree`). A pleasant consequence: a conflicted set costs milliseconds and never touches the filesystem, and a clean set yields a real commit, so the worktree step becomes a checkout rather than a sequence of merges.

## D14 — Validation is an ordered sequence of named stages (found by TEST)

Real projects do not have "the test command". On the repository TEST measured, `pnpm run build:cosmos` is a *prerequisite* of testing — without it seven test files fail to collect — so a validator that ran only the test command would report a false failure. And the expensive step is not the tests (9 s) but the install (33 s), which only needs to run when the lockfile moves.

So a validator is a list of `ValidationStage(name, command, fingerprint=, required=)`. The failing stage's name is prefixed onto every failure id, keeping "failed to build" distinguishable from "tests failed" in the log; a fingerprinted stage re-runs only when its inputs change; and `reuse_worktree=` keeps one tree for the whole run so the install is amortized. Lint is a non-required stage by default, matching how the repository's own CI gates.

## D15 — Stacks are a forest, and the constraint lives in the core (found by TEST)

TEST's framing, adopted verbatim: **a valid candidate set is downward-closed under the parent relation**. Not "a prefix of a chain" — stacks branch, so siblings share a parent. Four consequences, all in `mergeset/stacks.py`: close a set before evaluating it; drop a change's whole descendant cone when dropping it; merge only the *tips*, since a tip brings its ancestors (15 changes became 6 merges); and weight a change by its cone, or the hitting set will drop a stack root believing it dropped one small PR. On the observed forest this cut the search space from 32768 subsets to 576.

Shrinking must respect the closure too. QuickXplain proposes arbitrary subsets, and an arbitrary subset of a stack is a fiction: `{577, 587}` and `{575, 577, 587}` and `{575, 576, 577, 587}` all produce the same merged tree, so TEST's log recorded two duplicate evaluations under different labels. The solver now closes every subset before evaluating it, which both makes the log honest and collapses those onto one cache entry.

## D16 — A forge's CI verdict is only trusted when the bases agree (found by TEST)

GitHub reported PR PR-07 as `MERGEABLE` / `CLEAN` while it would not merge onto `main` at all — because GitHub was evaluating it against its own base branch, which had moved on. `analyze` compares each change's `base_ref` against the base being merged onto and ignores the forge's signal when they differ, saying so in the report. TEST rates this the single highest-value cheap check in the run: it excluded one change and its whole cone before any test.

## D17 — "Could not run the experiment" is not "the experiment failed" (found by TEST)

TEST passed a bad `reuse_worktree` and got a confident report: *Plan 1 — merge 0 of 15 · 24 expensive evaluations spent · complete*. Every checkout error had been recorded as a textual merge conflict. Three changes:

- `MergeOutcome.reason` is `'conflict'` or `'error'`, and only a conflict may enter the conflict set.
- An error produces `Verdict.ERROR`, and the search **aborts** on the first one. Continuing past an untestable evaluation manufactures conflicts out of infrastructure problems.
- `reuse_worktree` is validated (absolute path, real worktree) with an error message naming the fix — the original failure was passing `True` to an `Optional[str]`.

The tell in the bad reports was that `conflicting_files` was empty; a real textual conflict always names files.

## D18 — The base is evaluated before anything else

One evaluation of the empty set, on base alone. If the base does not validate, every subsequent failure is meaningless and "nothing can be merged" gets reported as a finding rather than as the misconfiguration it is. It would also have caught an earlier run where `detect_runner` classified a TypeScript repository as pytest — it checked for a `tests/` directory before looking at `package.json` — and ran pytest in it for twelve evaluations. `detect_runner` now ranks manifests above directory names, and the default validator refuses to guess rather than running the wrong command.

## D19 — File-overlap components are a search strategy, not a soundness claim (found by TEST)

The original version combined per-component results and presented the combination as an answer. TEST produced the counterexample: `{PR-04, PR-12}` is a real conflict spanning two components — PR-12's drift test asserts that committed schema artifacts match TypeScript sources, and PR-04 edits those sources while touching none of PR-12's files. No evaluated subset had ever contained both, so the tool recommended a 13-change plan that fails.

Decomposition is sound for *textual* conflicts and unsound for anything a whole-repo run can see: generated artifacts, barrel exports, snapshots, type checks, project-wide lint. It is kept, because finding a conflict inside a small component is finding it cheaply — but it now only *seeds*. The components are searched first, and then a global search runs with every conflict they found already known, so it starts nearly finished. A validator may opt out by declaring `validate.component_local = True` (as `merge_only_validation` does), and the "combine freely" claim was removed from the report unless that declaration is present.

## D20 — The oracle's failure output attributes blame (fixtures from TEST)

`mergeset/attribution.py` mines a failure for the changes it implicates, using three signals in increasing order of strength: every path in the failure block (source frames included, not just the failing test's file); the changes that touched those paths; and — decisively — the identifiers the output names, matched against each candidate's *added* diff lines.

The third signal is not a refinement. In TEST's `{PR-04, PR-12}` case the failing test lives in a file PR-12 added, while the culprit PR-04 shares no file with it, so file-level attribution accuses the innocent change; only matching `pointColorRedacted` / `pointColorRedacted` / `AxisDirectionType` against the diffs finds PR-04. In the `{PR-03, PR-06}` case four suites fail to *collect*, so there are no test ids at all — just a stack trace whose actionable frame is a source file. Both fixtures live in the local artifact store (`fixtures/` sub-store, see `docs/DECISIONS.md` D-storage) and are the tests. They are *not* committed: they are captured output from a private repository, and this repository is public.

Attribution is only ever a *hint*: it narrows the shrink, and a wrong hint costs one wasted check before falling back to unguided halving. It never decides a verdict.

## D21 — An empty log is still a log

`log = log or EvaluationLog(...)` silently discarded a caller-supplied log, because `__len__` makes an empty one falsy — on the first run, which is the run where it matters. `EvaluationLog.__bool__` now returns True, and the call site tests `is None`.


## D22 — The CLI can describe a real project, not only an easy one (found by TEST)

TEST's verification run reached the hand-derived answer exactly, and then reported the gap that mattered: the CLI could offer only `--merge-only`, one `--validate-command` string, or pytest. For the repository under test, the only expressible option was chaining install && build && test && lint into a single string, which throws away everything the staged validator exists for.

So `--validate-stage 'name:command'` is repeatable and ordered, `--validate-fingerprint 'stage:path'` makes a stage skippable, `--validate-optional name` makes one advisory, and `--reuse-worktree` is now a CLI flag too — without it the fingerprint has nothing to persist across. `--validate-command` remains the shorthand. The point is stated in the docs as well as the code: a chained string costs a re-run of the install per evaluation, collapses build and test failures into one exit code, and turns an advisory lint into a veto.

**And a correction while implementing it:** `required=False` used to record a stage's failure *and still fail the set*, which made the flag nearly useless — an advisory lint would have excluded every candidate. A non-required stage's failure is now recorded in `failing_tests` while the set still counts as good.

## D23 — A refusal is a result, not a traceback

`MergesetError` escaped the CLI as a stack trace with the reason at the bottom. It is now caught and rendered like any other outcome, and the detail is the most specific thing available: failing test ids when the runner named some, otherwise the exit code and the last lines of what it printed — because "exit 1 and nothing else" is exactly the case where a bare verdict leaves the user with nowhere to look.

## D24 — Nothing is reported twice under two explanations (found by TEST)

A change that will not merge onto the base at all was listed under "will not merge", and then again under "conflicts found by validation" — where it had no business, since nothing was ever run on it. The second section now excludes any conflict already explained by a textual clash or a singleton merge failure. In the same spirit, the `evaluated` progress event carries `cached`, so a caller can tell a free cache hit from a real, minutes-long run; the CLI's progress output no longer prints them, which had made the shrink look as if it were re-running the same set repeatedly.

## D25 — Nothing is recommended that was never evaluated as a whole

The defect TEST found first was that a combined plan could be recommended without ever having been run: the tool splits candidates into components that share no changed file, solves each, and combines the answers. `{PR-04, PR-12}` sit in different components, so no evaluated subset ever contained both, and the emitted "merge 13 of 15" was a set the tool had never seen. It fails. File-overlap decomposition is sound for *textual* conflicts and unsound for anything a whole-repo test run can see — a drift test in one component reads generated artifacts derived from sources another component edits, with no file in common.

The guard for that is a global search seeded with every conflict the components found cheaply, so the answer is established rather than composed. That guard has been in place since v1, and `test_components_are_not_assumed_to_combine_for_a_whole_repo_validator` gates it.

**It had a hole, and the hole had the same shape as the original bug.** When the global search hit a budget (or aborted) before finding a single passing set, `analyze` fell back to the cartesian combination — which had still never been evaluated. Reproduced: two components, a whole-repo validator, `max_evaluations=1`. The tool recommended `{feat-b, feat-d}` while its own log recorded that exact set as **FAIL**, with no note saying anything was wrong. A budget is not an exotic condition; it is the normal operating mode of this tool.

Three changes, none of which relies on the search behaving well:

1. **The log has the last word.** The fallback drops any combined set the log refutes, and says which and why. Recommending a set recorded as failing is now impossible by construction, not by good behaviour upstream.
2. **When nothing combinable survives, report what was established** — `log.maximal_passing_sets()`, every one of which has a recorded PASS. Smaller than the answer, and true; that is the right trade, and it beats both "no good set was found" and a confident lie.
3. **Every plan carries `verified`**, computed from the log — an exact recorded PASS, never inference across the monotone closure. An unverified plan is labelled `NOT VERIFIED` in both reports and ranks last however cheap it looks, because a plan nobody ran is not a better answer than a smaller one somebody did. A validator that declares `component_local` is taken at its word and nothing is flagged: there, combining is sound by contract.

Rank is now assigned *after* ordering. It was assigned before, so "Plan 1" was not necessarily the first plan the reader saw — harmless while the two orders happened to agree, and actively misleading now that unverified plans are pushed to the end.

The invariant worth stating plainly, because it is what the tool is for: **every set `mergeset` recommends has been merged and validated as a whole, or is labelled as not having been.** There is no third case.
