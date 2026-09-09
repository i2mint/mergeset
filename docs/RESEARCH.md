# Research: what "which branches merge together" already is, and what to borrow

> **A note on the trial run.** These decisions were made while analysing a real
> repository with 15 open pull requests. That repository is **private**, so its
> pull requests appear here as `PR-01`…`PR-17` and its identifiers are described
> rather than named. The reasoning is unchanged; only the labels are. Derived
> artifacts from that run — reports, logs, fixtures — are not in this repository
> at all, and must not be: see the `app-data-lifecycle` skill, "provenance
> outranks everything".


This document exists so the next person does not re-derive the theory. The problem `mergeset` solves has been solved twice already in other fields — once in constraint solving, once in merge-queue engineering — and the useful work is knowing which parts to lift and which parts not to depend on.

## 1. The problem is an independence system, and the objects have names

Fix a base commit and *n* candidate changes. A subset *S* is **good** if merging all of *S* onto base yields a tree that validates. Good sets are (approximately) downward-closed: subsets of good sets are good, supersets of bad sets are bad. That structure is an **independence system**, and it has been studied for decades under names worth using, because using them buys the literature:

| our word | SAT/CP literature | meaning |
|---|---|---|
| maximal good set | **MSS** — maximal satisfiable subset | good, and cannot be grown |
| conflict | **MUS** — minimal unsatisfiable subset | bad, and every proper subset is good |
| the set we drop | **MCS** — minimal correction set | complement of an MSS |

The two dual objects are tied together by **Reiter's hitting-set duality** [1]: the MCSes are exactly the minimal hitting sets of the MUSes, and vice versa. Reiter introduced this for model-based diagnosis in 1987 along with the HS-tree, the breadth-first search over hitting sets that `mergeset.solve.minimal_hitting_sets` implements (with a weight-ordered priority queue instead of level order, so the cheapest drop is proposed first).

This duality is the entire reason the search is tractable. We never enumerate subsets. We enumerate *reasons to drop things*, which is a much smaller set, and each one hands us a candidate for free.

## 2. MUS/MSS enumeration: MARCO, and why we did not depend on a solver

**MARCO** [2] is the canonical enumeration algorithm, from Liffiton, Previti, Malik and Marques-Silva (*Constraints* 21(2), 2016; it merges two independently-proposed approaches). It maintains a "map" formula over the powerset of constraints, marking regions already explained; each iteration asks the map for an unexplored seed, tests it, and then either grows it to an MSS (blocking its down-set) or shrinks it to an MUS (blocking its up-set). Its properties are exactly the ones we need: it is **anytime** (MUSes come out steadily rather than all at the end), it is **constraint-agnostic** (the oracle can be anything, which for us is a test suite), and it is indifferent to which single-MUS extractor you plug in. The reference implementation is [liffiton/MARCO](https://github.com/liffiton/MARCO).

`mergeset` implements the same loop with one substitution: the map formula is replaced by explicit enumeration of minimal hitting sets. That is a worse asymptotic idea and a better engineering one, for a reason specific to this problem — *n* is small (a dozen or two open PRs, not a hundred thousand clauses) while each oracle call is minutes. Every design decision should buy oracle calls at the expense of anything else, and at *n* ≈ 20 the hitting-set enumeration is microseconds. It also keeps the map inspectable, which matters because the output is a report a human has to trust.

**Shrinking a failure to a conflict** uses **QuickXplain** [3] (Junker, AAAI 2004): recursive halving that isolates a minimal conflict in *O*(k log(n/k)) oracle calls for a conflict of size *k*, against *O*(n) for removing elements one at a time. On a 15-change set with a 2-change conflict that is roughly 6 evaluations instead of 15 — an hour saved at 45 s each. `mergeset` ships both (`quickxplain` and `shrink_linear`) and tests them against each other, because the naive one is the referee.

**Should we depend on PySAT?** [4] (Ignatiev, Morgado, Marques-Silva, SAT 2018) is excellent and ships `mcsls`, `lbx`, `musx` and `optux` as ready-made enumerators. We do not depend on it, for three reasons. (a) Our oracle is a subprocess running a test suite, not a SAT solver, so the SAT machinery would only be modelling the *map*, which is the cheap half. (b) `python-sat` pulls compiled solver binaries — a heavy dependency for a tool whose value proposition is "point it at a repo and run". (c) The loop is ~100 lines and we need to modify it anyway, for the stack constraint (§5) that has no clean encoding in an off-the-shelf MCS enumerator. The judgement would flip if *n* reached the hundreds.

**Delta debugging.** `ddmin` [5] (Zeller and Hildebrandt) and its parallel Python implementation **picire** [6] solve a genuinely adjacent problem: minimize a failing input while it still fails. `ddmin` differs from QuickXplain in that it also tries *complements* and increases granularity on failure, which buys robustness when the property is not monotone. We do not depend on picire — it is built around characters and lines of a test input, and adapting it costs more than the 20-line `quickxplain` — but its complement-testing idea is the right thing to reach for if monotonicity violations (§6) turn out to be common in practice.

## 3. Combinatorial group testing: what to do with parallel machines

If *k* evaluations can run at once, the question stops being "which subset next?" and becomes "which *batch*?". That is **combinatorial group testing**, which dates to Dorfman's 1943 scheme for pooling blood samples [7]: test a pool, and only if the pool is positive test its members. The adaptive version is exactly the halving in QuickXplain. The **non-adaptive** version — fix all pools in advance so they can run simultaneously — is what a build farm wants, and the relevant bound is that *d* defectives among *n* items need *O*(d² log n) non-adaptive tests, versus *O*(d log n) adaptive ones. That gap is the price of parallelism, and it is usually worth paying when the machines are already idle.

The practical shape for `mergeset`: when the concurrency budget is *k*, take the *k* cheapest not-yet-blocked hitting-set complements rather than only the cheapest, and shrink whichever of them fail. The `concurrency` seam is designed for this; the batch policy is not yet implemented and is the clearest next feature.

## 4. Merge-queue prior art: what the industry actually does on failure

Merge queues answer a strictly easier question — "can this *ordered list* land?" — but they have paid for their lessons in production.

**Zuul** [8] (OpenStack) gates changes with speculative dependent pipelines: change *n* is tested against a tree that already contains changes 1…*n*−1, so the queue tests the future rather than the past. On failure it *resets* the queue from the failing change onward, discarding the speculative work behind it. **Bors** [9] (of Rust fame) is the minimal honest version: batch changes, test the batch, and on failure **bisect the batch** — which is `ddmin` under another name, and confirmation that the halving instinct is right. **GitHub's merge queue** [10] is the productized form of Zuul's idea, with a configurable number of PRs built speculatively at once.

**Uber's SubmitQueue** [11] (Ananthanarayanan et al., ICSE-SEIP 2019) is the one worth reading in full, and it contributes the two ideas we most want:

1. **A probabilistic model over the speculation tree.** Speculating on every possible future is exponential, so SubmitQueue estimates the probability each build passes and only expands the likely branches. The follow-on work reports ~53% less CI resource usage from adding a speculation threshold and modelling build duration [12].
2. **Conflict analysis to prune before speculating.** Changes that touch no shared build target are independent and may be evaluated concurrently. This is precisely our file-overlap decomposition (`independent_components`), and their experience is the evidence that it is worth doing at *build-target* granularity rather than file granularity when a build graph is available.

What we take: speculate cheaply and prune structurally before spending machines; bisect a failing batch; treat independence as the primary lever. What we deliberately do *not* take: the queue framing itself. A merge queue answers "may this land now?" one change at a time; `mergeset` answers "what is the largest set that can land at all?", which is the question you ask when *n* changes are already in flight and you want a plan, not a turnstile.

## 5. Git mechanics, and the one that is easy to get wrong

**`git merge-tree --write-tree`** [13][14] (git ≥ 2.38) performs a real three-way merge — the `ort` strategy, with rename detection, directory/file conflict handling and recursive ancestor consolidation — writing the result into the object database and touching neither the index nor the working tree. It exits non-zero on conflict and prints the conflicted paths. This is why the cheap pre-oracle is cheap: milliseconds per pair, no checkout.

**The trap.** `git merge-tree A B` merges using `merge-base(A, B)`. When the candidates were cut at different times — i.e. one is stale — that merge base is *older than the base you care about*, and the base branch's own commits get reported as conflicts. Measured on a real 15-PR set, the naive pairwise sweep reported **13 conflicting pairs where only 2 were real**; eleven false positives from a single stale branch. The fix is to chain through base:

```
acc = base
for each head:  tree = merge-tree --write-tree acc head ;  acc = commit-tree tree -p acc -p head
```

*n* merge-tree calls, still milliseconds each, still no working tree — and the result is a real commit, so a worktree is only ever created for a set that actually merged and actually wants testing. `mergeset.gitops.merge_sequence` is this loop, and every other git operation in the package goes through it. (Found by the TEST workstream; see `docs/adr/0013-*`.)

**Worktrees versus temp clones.** `git worktree add --detach <dir> <commit>` shares the object database with the origin repository, so it costs a checkout rather than a clone, and several can exist at once for parallel evaluation. Temp clones are only preferable when the validation step might corrupt the repository or needs its own remote configuration. The one real cost of worktrees is per-tree *setup* — `npm install`, virtualenvs, build caches — which is why `mergeset` supports reusing a single worktree across evaluations and fingerprinting the setup stage on its inputs (`file_fingerprint('pnpm-lock.yaml')`), so a 33-second install is paid when the lockfile moves rather than on every candidate.

**Stacked branches** are the structural case the theory ignores. A PR based on another PR already contains it, so the candidate set is not an antichain and arbitrary subsets are not meaningful: valid sets must be **downward-closed** under the parent relation, and since stacks branch, that is a forest and not a chain. Three consequences, all implemented in `mergeset/stacks.py`: close a set before evaluating it; merge only the *tips*, since a tip brings its ancestors; and weight a change by its whole descendant cone, or the hitting set will drop a stack root believing it dropped one small PR. The size reduction is dramatic — on a 15-change forest of four stacks, 576 valid sets rather than 32768 subsets.

A related trap, same family: a forge's `mergeable`/CI verdict is computed against the PR's **own** base branch. A PR can report CLEAN on GitHub and refuse to merge onto `main`, because its base branch moved on without it. The signal is only usable as a pre-oracle when the bases agree.

## 6. Making each evaluation cheaper, and monotonicity

**Test-impact selection.** The static version — run only tests reachable from the changed files — is what the `select_paths` seam in `pytest_validation` exists for. The learned version is Facebook's **Predictive Test Selection** [15] (Machalica et al., 2018): train on historical test outcomes to predict which tests a change can break, then run only those. Deployed, it halved testing infrastructure cost while still reporting >95% of individual test failures and >99.9% of faulty changes. Two things make it directly relevant here. First, it is explicitly *probabilistic* — it accepts missing a small fraction of failures — which is the right trade for our use because a missed failure means one wrong entry in a report a human reviews, not a broken trunk. Second, it models **flakiness** as a first-class phenomenon, which is exactly what breaks our monotonicity assumption.

**Monotonicity is a prior, not a law.** It fails in two ways. Benignly: a change contains the fix that makes another change work, so a superset of a bad set passes. Malignly: a flaky test makes the same set pass and fail. Since the whole search rests on propagating good/bad verdicts through the subset lattice, a violation invalidates conclusions silently unless it is looked for. `mergeset` records every evaluation in an append-only log and checks it for contradictions (`EvaluationLog.monotonicity_violations`), reporting them loudly rather than smoothing them over; `flake_tolerant(validate, retries=n)` is the cheap mitigation and pinning changes as always-included is the escape hatch.

**The oracle should return a record, not a bit.** A failure that names the failing tests lets us map tests → files → the changes that touched those files, and aim conflict-shrinking at the suspects instead of halving blindly. This is not theoretical: in the trial run both semantic conflicts (a schema-drift test failing because a sibling PR added config without regenerating; four test files failing to load because a barrel-export refactor left an enum undefined at module evaluation time) were identified directly from the failing test identities, where blind halving would have cost several more runs at ~45 s each.

## What we use, and why

| we use | instead of | because |
|---|---|---|
| our own ~100-line MARCO-shaped loop | PySAT / `python-sat` | the oracle is a test suite, not a SAT solver; the map is the cheap half; compiled solver binaries are a heavy dependency for *n* ≈ 20; and the forest constraint needs a modified loop |
| QuickXplain | ddmin / picire | *O*(k log n) vs *O*(n) oracle calls, 20 lines, no dependency; `shrink_linear` stays as the referee |
| Reiter HS-tree, weight-ordered | a SAT map formula | *n* is small, it is microseconds, and the map stays inspectable — which matters because a human reads the output |
| `git merge-tree --write-tree`, chained through base | pairwise merge-tree; worktree merges | milliseconds, no filesystem, and chaining is the difference between 2 real conflicts and 13 phantom ones |
| SubmitQueue's independence pruning (at file granularity) | speculating over all orderings | it is the single biggest structural win and needs no build graph |
| staged validation with a fingerprinted setup | one test command | a build is a prerequisite of testing, not part of it, and a 33 s install must not be paid per evaluation |
| the evaluation log as SSOT | in-memory state | re-runs are free, crashes resume, reports regenerate, and monotonicity violations become detectable |
| `cw` | `argh` | MIT with zero runtime dependencies, versus LGPL-3.0-or-later |

Total runtime dependency count: one (`cw`), and the core library works without it. That is deliberate. The algorithm is small and the value is in the git mechanics and the cost ordering, neither of which any dependency would have supplied.

Open, and next: the non-adaptive batch policy for parallel evaluation (§3); learned or static test-impact selection to make each evaluation cheaper (§6); and mapping failing test identities back to the changes that touched those files, which is the highest-value use of information the oracle already returns.

## REFERENCES

1. Reiter R. A theory of diagnosis from first principles. *Artificial Intelligence*. 1987;32(1):57-95. [ScienceDirect](https://www.sciencedirect.com/science/article/pii/0004370287900622)
2. Liffiton MH, Previti A, Malik A, Marques-Silva J. Fast, flexible MUS enumeration. *Constraints*. 2016;21(2):223-250. [Springer](https://link.springer.com/article/10.1007/s10601-015-9183-0) · implementation: [liffiton/MARCO](https://github.com/liffiton/MARCO)
3. Junker U. QUICKXPLAIN: preferred explanations and relaxations for over-constrained problems. In: *Proc. AAAI-04*. 2004:167-172. [AAAI](https://cdn.aaai.org/AAAI/2004/AAAI04-027.pdf)
4. Ignatiev A, Morgado A, Marques-Silva J. PySAT: a Python toolkit for prototyping with SAT oracles. In: *Proc. SAT 2018*. LNCS 10929:428-437. [preprint](https://alexeyignatiev.github.io/assets/pdf/imms-sat18-preprint.pdf) · [docs](https://pysathq.github.io/) · [PyPI](https://pypi.org/project/python-sat/)
5. Zeller A, Hildebrandt R. Simplifying and isolating failure-inducing input. *IEEE Trans. Software Engineering*. 2002;28(2):183-200. [The Debugging Book](https://www.debuggingbook.org/html/DeltaDebugger.html)
6. Hodován R, Kiss Á. Practical improvements to the minimizing delta debugging algorithm. In: *Proc. ICSOFT-EA 2016*. [PDF](https://www.scitepress.org/papers/2016/59886/59886.pdf) · implementation: [renatahodovan/picire](https://github.com/renatahodovan/picire)
7. Dorfman R. The detection of defective members of large populations. *Annals of Mathematical Statistics*. 1943;14(4):436-440. [Project Euclid](https://projecteuclid.org/journals/annals-of-mathematical-statistics/volume-14/issue-4/The-Detection-of-Defective-Members-of-Large-Populations/10.1214/aoms/1177731363.full)
8. Zuul project. Gating and dependent pipelines. [Zuul documentation](https://zuul-ci.org/docs/zuul/latest/gating.html)
9. Bors / bors-ng. Batching and bisection on failure. [bors-ng](https://bors.tech/)
10. GitHub. Merging a pull request with a merge queue. [GitHub Docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
11. Ananthanarayanan S, Ardekani MS, Haenikel D, et al. Keeping master green at scale. In: *Proc. EuroSys 2019*. [ACM](https://dl.acm.org/doi/pdf/10.1145/3302424.3303970) · summary: [the morning paper](https://blog.acolyer.org/2019/04/18/keeping-master-green-at-scale/) · code: [uber/submitqueue](https://github.com/uber/submitqueue)
12. Uber Engineering. CI at scale: lean, green, and fast. 2025. [arXiv:2501.03440](https://arxiv.org/html/2501.03440) · [Bypassing large diffs in SubmitQueue](https://www.uber.com/us/en/blog/bypassing-large-diffs-in-submitqueue/)
13. Git project. git-merge-tree(1). [git-scm.com](https://git-scm.com/docs/git-merge-tree)
14. GitHub Blog. Highlights from Git 2.38. 2022. [github.blog](https://github.blog/open-source/git/highlights-from-git-2-38/)
15. Machalica M, Samylkin A, Porth M, Chandra S. Predictive test selection. 2018. [arXiv:1810.05286](https://arxiv.org/abs/1810.05286) · [Meta Research](https://research.facebook.com/publications/predictive-test-selection/)
