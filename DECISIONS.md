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

`.mergeset/evaluations.jsonl`, one JSON object per evaluated set. Everything else — the conflict set, the known-good/known-bad closure, the merge plan, both reports — is *derived* and re-derivable, so a report can be regenerated without re-running anything and a crashed run resumes for free.

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
