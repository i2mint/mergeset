---
adr: 0026
title: "Validation is not uniform cost: tiered oracles, a measured cost model, and an anytime search"
status: accepted
date: 2026-09-09
issue: i2mint/mergeset#13
builds_on: 0025   # nothing is recommended that was never evaluated as a whole
# No `decision:` field: this record was written after the DECISIONS.md split, so
# it has no pre-split `D<n>` identifier for older references to resolve against.
---

# 0026 — Validation is not uniform cost: tiered oracles, a measured cost model, and an anytime search

## Context

`mergeset` prices every evaluation the same. One candidate set costs one suite run, and the search spends its budget in units of "evaluations" because that unit was, until now, honest: there was one suite, it took about forty-five seconds, and the only interesting question was how many times to run it.

That assumption has broken. In the current scope one candidate change requires an **end-to-end** validation tier — containers, a database, a headed browser — measured in minutes rather than seconds, on infrastructure that is not always present. The last run dealt with this by excluding that change from the candidate set. Excluding a candidate because validating it is expensive is not a strategy; it is the answer to a different question, delivered without saying so.

The situation will recur and it is not one-dimensional. Some changes are heavy. Some *tiers* are heavy. Some tiers are flaky. Some need resources that come and go. A search told to treat all of that as one number will keep spending its budget in the wrong place, and — worse — will keep reporting confident answers about experiments it never ran.

Three facts about the problem shape everything below. All three are established, not assumed.

- **The predicate is monotone.** If a set fails, every superset fails. Sixteen evaluations of a real eighteen-change run held this throughout, and `EvaluationLog.monotonicity_violations()` polices it rather than trusting it (ADR-0005).
- **The tiers are monotone in each other.** A cheap-tier failure implies overall failure. So a cheap tier is a **sound filter**, and an expensive tier only ever needs to run on cheap-tier survivors. This is the single largest lever available and it is currently unused.
- **Textual pre-oracles are not enough, and neither is decomposition.** File-overlap decomposition is sound for textual conflicts and unsound for anything a whole-repo test run can see; that was the defect fixed in #9 (ADR-0019, ADR-0025). Semantic conflicts — a drift test guarding artifacts generated from sources another change edits; a barrel export whose evaluation order changes — are invisible to any merge-level check, and pairwise-green does not imply set-green.

Measured on the run in progress, with the staged validator and a reused worktree: the merge itself costs 0.21–0.69 s against 27–51 s of validation. **Merging is free and validating is everything — three orders of magnitude apart.** A cost model that prices merges is pricing noise; the interesting axis is entirely inside the validator.

Splitting those timings by set size is what the design turns on:

```
size 0   (the base check):  51.2 s                                      -- one point
size >=1 (the body, n=9):   27.2 30.2 30.7 31.0 31.6 32.8 34.8 36.9 37.2
                            mean 32.5, sd 3.1
```

The base check is not a small candidate set. It is the first evaluation, so it is the one that always pays the cold dependency install that every later evaluation skips through a fingerprinted setup stage. It is therefore simultaneously at the extreme of the independent variable (size 0) and the slowest run — which is exactly the shape that dominates a linear fit.

## What the literature already solves — and what it does not

Thor asked specifically whether this has been researched. Most of it has, in three separate literatures that have not been pointed at each other.

**The search itself is a solved problem with a name.** What `mergeset` computes is a *maximal satisfiable subset* (MSS) enumeration; the complements are *minimal correction sets* (MCSes), and the conflicts are *minimal unsatisfiable subsets* (MUSes). Reiter's hitting-set duality [1] is why enumerating cheapest-first hitting sets of the conflicts yields the maximal good sets — which is precisely what `solve.py` does. CAMUS [2] computes all MCSes and then derives MUSes as their irreducible hitting sets. MARCO [3] is the modern reference: constraint-agnostic, needing only a monotone yes/no oracle, and explicitly **anytime** — it produces results steadily rather than only at the end. Junker's QuickXplain [6] is the `O(k log(n/k))` conflict minimizer already in `solve.py`.

**The abstraction is also named.** Marques-Silva, Janota and Belov's *Minimal Sets over Monotone Predicates* (MSMP) framework [4] observes that MUS, MCS, prime implicate and minimal model extraction are all one problem — find a minimal set subject to a monotone predicate — and gives an asymptotically optimal algorithm in oracle queries. Janota and Marques-Silva later settled the query complexity of selecting minimal sets for monotone predicates [5]. **`mergeset` is an MSMP instance where the oracle is a git merge plus a test suite.** That framing is worth adopting in the vocabulary, because it makes clear which parts are already optimal and which are not: everything above counts *oracle queries*, and treats every query as costing the same.

**Delta debugging is the same shape from the other end.** `ddmin` [7] minimizes a failing input under a monotone predicate; ProbDD [8] replaces its fixed removal schedule with a probabilistic model that picks the next test to maximise expected gain, taking the worst case from `O(n²)` to `O(n)`. ProbDD is the closest existing thing to "choose the next query by expected value" in this family — but its notion of gain is *information*, not *seconds*, and every test is still assumed to cost the same.

**Cost-awareness exists — in the testing literature, about a different object.** Time-aware test suite prioritization [13] and cost-cognizant prioritization (the `APFDc` line of work by Elbaum, Malishevsky and Rothermel) build a per-*test-case* cost model and order tests within a budget. Predictive test selection [15] learns from historical outcomes which tests to run per change and cut Facebook's testing cost in half while still reporting >95 % of individual failures — an *unsound* filter with a measured miss rate. Batch testing [16] runs several commits together and bisects on failure, which is the same monotone reasoning `mergeset` does, applied to a queue rather than to a set. All of this prices *tests*. None of it prices *oracle queries in a maximal-subset search*.

**The "expensive test, chosen well" problem is solved in yet another literature.** Sequential testing of Boolean functions [19] and stochastic Boolean function evaluation [18] are exactly "evaluate a monotone function when each probe has its own price", with approximation algorithms and hardness results. De Kleer and Williams' sequential diagnosis [22] chooses the next measurement by expected cost. Adaptive submodularity [17] gives a `(1 - 1/e)`-competitive adaptive greedy for budgeted adaptive selection. These are the right tools for "which expensive evaluation next", and none of them has been pointed at MSS enumeration.

**Speculative merging is the closest software-engineering ancestor.** Crystal / *Proactive detection of collaboration conflicts* [11,12] does not predict conflicts: it speculatively merges, builds and tests in the background, and it established that conflicts show up as build and test failures, not only as textual overlaps — the same finding this project re-derived. It speculates over *pairs*, and explicitly notes the combinatorial cost of going further. It has no cost model.

**Industrially, the batching half is standard practice and the search half is not.** Merge queues (GitHub, Mergify, Aviator, Trunk) batch pull requests into one CI run and bisect on failure; at least one documents reusing the parent batch's result to avoid re-running tests that already passed on the larger batch [23] — monotone reasoning, in production, undocumented as such. None of them searches for the *maximal* mergeable subset, and none exposes a cost model.

### So what is actually missing

Three things, and they are the contribution of this ADR:

1. **MSS/MCS enumeration with a non-uniform oracle.** Every algorithm above counts queries. Nothing in the MUS/MSS literature I can find treats query cost as an input, and the surveys of MCS enumeration improvements are about caching and solver reuse [10], not about price. "Tunable online MUS/MSS enumeration" [9] is the nearest neighbour — it lets you trade completeness for throughput — but the knob is a strategy, not a cost model.
2. **A *tiered* oracle, exploited as a sound filter for the search interior.** Abstraction–refinement is old in SAT, and staged CI pipelines are old in industry, but the specific composition — *use the cheap tier's MSS frontier as the only place the expensive tier is ever allowed to run* — is not written down for this problem, and it is the whole game. The lemma that licenses it is one line (below).
3. **The honest accounting for what "verified" means when tiers differ.** Nothing in the literature needs this, because a SAT oracle does not have tiers. This repository does, and it has already been burned once by reporting a set assembled from parts nobody ran (#9, ADR-0025).

Everything else here is assembly of existing parts, and is documented as such.

## Options

**Keep excluding expensive changes.** Costs nothing, answers a different question than the one asked, and says so nowhere. It is what happened last time, and it is what this ADR exists to replace.

**Run the expensive tier everywhere.** Correct and unaffordable: on the current scope it multiplies a ~10-minute run into hours, and it fails outright when the tier's infrastructure is down.

**One composed validator that short-circuits.** Chain the tiers inside a single `ValidationOutcome`-returning function — a cheap failure returns early and the expensive tier never runs. This is a genuinely good idea and it gets most of the arithmetic: on the observed run it would pay the deep tier about four times instead of sixteen. It gets **none of the control**: one blended duration in the log instead of per-tier cost data, one boolean instead of a per-tier verdict, no way to spend a deep budget on the best two candidates only, no degradation when the deep tier's infrastructure is absent, and no way to add a tier later to results you already have. Rejected for those four reasons, not for its arithmetic.

**Predict which sets need the expensive tier.** A learned filter in the style of [15], or a declared "this tier is only relevant to these changes". Both are *unsound* — they are the file-overlap decomposition bug (#9) one level up, and this repository has already paid for that mistake once. Rejected as a default; see Rejected alternatives for the conditions under which it could return.

**Screen with the cheap tier, confirm on the frontier.** Sound, cheap, anytime, and degradable. Chosen.

## Decision

### 1. Cost is a first-class input, and its default is measured

A **cost model** (`mergeset/cost.py`) is one keyword-only argument on the tiered facade. It answers three questions: what will this cost (`estimate`, used for *ordering*), what could it cost (`pessimistic`, used for *budget admission*), and where did that number come from (`is_measured`, `summary`).

The default is `MeasuredCost`, fitted by ordinary least squares to `(set size, seconds)` pairs — data the evaluation log has been recording since the package was written and then discarding. Two numbers per tier, from measurements you already have:

```
seconds(tier, subset) = intercept(tier) + slope(tier) · |subset| + per-change surcharges
```

Four properties are deliberate.

- **Measurements beat declarations.** A tier's declared `cost` prices it until it has been run; after that, observation wins.
- **An unmeasured, undeclared tier is not free.** It is priced at `UNMEASURED_TIER_SECONDS` (60 s, one keyword away), chosen to be wrong in the safe direction: high enough that a cost-ordered scheduler runs an untimed tier *after* every tier it has actually measured, low enough that a first run still happens. `inf` would be safer and would mean no new tier ever runs, which is a refusal rather than a model.
- **A cost model over CI timings has at least two regimes, because caching is what makes CI affordable.** Fitting one line through both inverts it: the size-0 point at 51 s against a body around 32 s produces a *negative* slope, so the model concludes that adding changes makes validation faster. Budgets survive that — the residual is enormous — but `estimate` drives **ordering**, and ordering was silently backwards, which is the worse failure because a wrong budget is visible and a wrong order is not. So the slope is fitted on the body only, the empty set is priced from its own regime rather than extrapolated, and a negative fitted slope degrades to the mean because adding a change cannot make validation faster.
- **Two estimates, because they are used for different decisions.** Ordering can afford to be wrong; a budget check cannot. `pessimistic` is the central estimate plus the worst residual *against the same model*, so it carries the spread **within** a regime — an install that ran because the lockfile moved, a slow runner — and never stands in for a regime that should have been separated.

**Price each regime where it occurs; reserve the expensive one explicitly.** This is the correction that matters, and it was nearly missed. Before the regimes were separated, the cold base check inflated `pessimistic`'s residual and so a warm-set budget happened to cover a cold run — by accident, and only until someone improved the fit. With the regimes separated the base check's residual is ~0, and a warm-set `pessimistic` of about 38.7 s (mean + 2 sd) falls **12.5 s short** of the 51.2 s a cold evaluation actually costs — roughly a third under. So `_runs_allowed` takes `reserve = pessimistic(tier, ∅)` off the budget before dividing: the tier's own base check is a real evaluation and the most expensive one it will run. Correctness that depends on an unrelated inaccuracy is correctness that evaporates the next time someone fixes something.

**Held as a hypothesis, not published as a law: the warm regime may be flat.** Across set sizes 1–13 the body's standard deviation is 3.1 s against a 27 s floor — a size-1 evaluation took 30.2 s and a size-13 took 34.8 s. On this evidence set size barely predicts cost at all; the dominant term is *which regime you are in*, and fitting a slope may be modelling noise. The slope is kept because it is guarded, costs nothing, and a validator that selects tests per change would genuinely have one — but this is **nine points on one repository**, and the honest reading is that the reserve is load-bearing while the fit is not yet demonstrated to be. Check it on a second project before treating the slope as real.

### 2. Validation is an ordered chain of monotone tiers

A `Tier` is a name, a validator (the existing `worktree -> ValidationOutcome` contract, so `staged_validation` and friends drop in unchanged), an optional declared cost, and an optional `available()` probe. Tiers are ordered cheapest-first.

**Each tier keeps its own evaluation log.** This is not tidiness. A cheap-tier PASS is not evidence about the expensive tier, so the two verdicts must not share a cache entry — and `verified` must mean *verified at the tier you are claiming*. `TieredAnalysis.verified_tier(subset)` returns the deepest tier with an **exact recorded PASS**; inference across the monotone closure deliberately does not count, exactly as in ADR-0025.

### 3. The algorithm: screen the interior, confirm the frontier

The lemma that licenses everything:

> **Every maximal good set of the full oracle is contained in some maximal good set of the screen.**
> If `S` passes every tier then it passes the screen, so it lies inside some maximal screen-passing set. ∎

An earlier draft of this record overstated the consequence as *"the expensive tier runs on the frontier and never on the interior"*. That is false, and measuring it says so: a conflict visible **only** to the deep tier has to be *shrunk* at deep prices, and QuickXplain's `O(k log(n/k))` queries are interior by construction. On eight branches with one deep-only conflict, 5 of 7 deep evaluations were interior. What survives is the useful half, and it is enough: **a set the screen refutes is never paid for at depth**, so the interior the *screen* explores is free, and deep spending is bounded by the frontier plus whatever genuine deep-only conflicts force. With no deep-only conflict it is the frontier and nothing else.

The maximal screen-passing sets are the **frontier**. There are usually a handful — four, on a real eighteen-change run. Everything else the search touches is *interior*: hitting-set probes, QuickXplain steps, growth checks. None of them can be the answer, and all of them are where the evaluations go.

So:

1. **Screen.** Run the ordinary search (`analyze`) with the cheap tier as its validator. The whole interior is paid at cheap-tier prices. Out come the frontier and every conflict found.
2. **Confirm.** Run the same search one tier deeper, through a *chained* evaluator that short-circuits on the first tier to fail, **seeded with every conflict the screen found**. It therefore starts almost finished, its candidates are frontier sets, and its interior is answered from the screen's log for nothing.

The composed evaluator is the mechanism; the seeded conflicts are what keep the deep search from re-deriving what a `merge-tree` call already knew. Expensive evaluations are spent on the frontier plus whatever conflict-shrinking a genuine deep-only failure requires — `O(k log(n/k))` deep queries per deep conflict, and every query inside the shrink is screened for free first.

On the observed run's shape that is roughly `21 × cheap + 4–8 × deep` in place of `21 × deep`.

**Every tier checks the base, not just the first.** ADR-0018 evaluates the base commit alone before anything else, so that a broken base or a wrong command is a refusal rather than *n* confident failures. That check lives inside `analyze`, which means only the screen got one — and a deep tier that is red on the base itself makes every frontier set fail, so the run reports "nothing passes `e2e`" as a **finding** rather than as the misconfiguration it is. That is worst exactly where it is hardest to catch: a tier expensive enough to need this design is a tier nobody can cheaply re-run by hand to cross-check. So each tier evaluates the empty set at its own depth before searching, and the budget reserves it.

It **skips** rather than raising, which is the one place this departs from ADR-0018. By the time a deep tier is reached the screen search is banked — often many minutes of it — and discarding a true answer in order to report a misconfiguration would be the worse trade. The depth label already says the tier confirmed nothing, and the reason names the tier and what it printed.

**A deep tier that cannot run is skipped, not degraded.** No container daemon, an authorisation that has not arrived, or a budget that will not admit one run, and stage 2 does not happen: the answer is the screen's, labelled with the depth it reached and routed through the existing `unverified_sets` machinery so every report already flags it. **A tier that did not run is not a tier that passed.** This is what makes a permanently-unrunnable tier representable rather than a caveat someone has to remember: `Tier(available=lambda: False)` turns "we cannot run e2e here" into a property of the answer instead of a sentence in a handover.

### 4. Anytime, with a certificate rather than an exhausted budget

After every stage, `AnytimeAnswer` reports:

- `best` — the heaviest set validated so far, and `best_tier`, the deepest tier that actually ran on it. Depth outranks weight: a set confirmed at the deepest tier is a better *answer* than a heavier set confirmed only at the screen.
- `bound` — the weight of the heaviest set **no known conflict forbids**, computed as the complement of the cheapest minimal hitting set of every conflict found at any tier or pre-oracle. Because every conflict refutes a real set, this is a genuine upper bound on the optimum, not a hope.
- `gap = bound − best_weight` — what might still be being missed.
- `pending` — the unconfirmed candidates, priced by the cost model. The answer to "what would closing the gap cost".

`gap ≤ 0` **together with full tier depth** is a certificate: the heaviest set nothing refutes has itself been validated, so nothing better exists. That is a stopping rule. A zero gap at the screen alone proves nothing, and is reported as not optimal.

This is the anytime/contract distinction from [20,21], instantiated: the search is interruptible, and the interruption is priced.

### 5. "Keep this change" is a second question, with a different answer

The current run makes this concrete, and it is not what anyone assumed. The end-to-end change conflicts **textually** with five others. The best validated set containing it is 11 of 18; the best validated set overall is 13 of 18. **The expensive tier's real cost here is not its runtime — it is that the change requiring it is nearly disjoint from the best plan.** A model that prices only seconds misses that entirely.

So `must_include` is a first-class parameter, and `best_set_including` enumerates the complements of minimal hitting sets that *avoid* the required changes. It reuses every conflict the main search found, so on the current data it costs a handful of evaluations, and it returns `None` — with the reason — when the required changes cannot all be kept, which is a finding and not a failure.

The two answers are reported side by side. A smaller answer to "what is the best plan that keeps this change" is not a worse answer.

## Thor's two-phase heuristic, assessed honestly

> *"Find the maximal set without the heavy one, then try to add it."*

**It is a lower bound, never an over-claim** — everything it returns was evaluated, which is ADR-0025 satisfied. And it is **better than it looks**, with a bound:

> **Proposition (deferred-change regret).** Let `U` be the candidates, `H ⊆ U` the deferred changes, `w ≥ 0` a weight, and `P` the monotone predicate. Let `M₁` be the heaviest `H`-free set with `P(M₁)`. Then for every `S ⊆ U` with `P(S)`: `w(S) ≤ w(M₁) + w(H)`.
>
> *Proof.* `S \ H` is `H`-free and `P(S \ H)` holds by downward closure, so `w(S \ H) ≤ w(M₁)`. Then `w(S) ≤ w(S \ H) + w(S ∩ H) ≤ w(M₁) + w(H)`. ∎

**So the regret of the two-phase heuristic is at most the weight of what you deferred.** With one heavy change and unit weights, the true optimum is *at most one change larger* than what two-phase reports — and this holds even for the literal single-set reading, which only tries the largest phase-1 set. It is **exactly optimal** whenever `M₁ ∪ H` passes, which is one evaluation to check, and in particular whenever the heavy change is in no minimal conflict.

That is a good heuristic. It has two failure modes, and only the second is the dangerous one.

**Failure mode 1 — it answers the global question, not the constrained one.** The bound is on the *global* optimum. It says nothing about the best plan that *contains* `H`, and that gap is unbounded. The current data is the counterexample: best overall 13 of 18, best containing the e2e change 11 of 18, and the 11-set is not reachable from the 13-set by adding or removing one member. If the heavy change has to land, two-phase does not answer the question. That is what §5 is for.

**Failure mode 2 — deferring a *tier* is not deferring a *change*, and only one of them is bounded.** The proposition needs `P` — the *full* predicate, every tier — evaluated on `H`-free sets. If phase 1 runs only the cheap tier, which is the whole reason anyone defers, then `M₁` is merely screen-maximal, the proposition does not apply, and what you are holding is an unvalidated set. **Deferring a change costs at most `w(H)`. Deferring a tier costs an unknown amount and, worse, is invisible.** Conflating the two is the trap, and separating them is the most useful single sentence in this ADR.

**When it is safe, concretely:** the two-phase heuristic is sound and within `w(H)` when (a) monotonicity holds — checked, not assumed, and `monotonicity_violations()` is the check; and (b) phase 1 ran *every* tier on the `H`-free sets. Under those two conditions, running it is a perfectly reasonable thing to do while a principled run is being built, which is exactly what is happening now.

## What an adversarial review changed

`landing-a-branch` requires an independent reviewer for a change of this size, briefed to **refute** rather than approve. It confirmed five defects that the branch's own green suite did not catch, and the two that matter most are worth recording because both are the *same shape as bugs this repository has already fixed once*:

- **A constrained answer could be a whole change short.** `best_set_including` returned the first passing proposal in hitting-set weight order — but stack closure shrinks proposals *after* that order is fixed, so the first passing one need not be the heaviest. `solve.py::_grow_within_known` exists for exactly this and says so in its docstring; re-implementing the search loop without it re-introduced the bug it documents. **Re-implementing a loop is re-implementing its bug fixes.**
- **Budget admission never read the deep tier's own log.** Costs were synced *after* a tier ran, so admission priced every deep tier from its declaration or the 60 s unmeasured default even when its log held dozens of real timings — a 600 s budget admitting 3000 s of work, while this document claimed "measurements from one run price the next".

Also fixed: two tier names differing only in case (`e2e`, `E2E`) shared one log on macOS and Windows — a cheap PASS answering an expensive question, on the default filesystem of two of three platforms; `confirm_budget_seconds` did not reach the `must_include` phase, leaving it uncapped at deep prices; and the report's *prose* claimed confirmation at the deepest tier whenever that tier had merely been entered, contradicting the `NOT VERIFIED` list three lines below it. The data was right and the sentence was wrong, which is the worse half — the sentence is what a reader believes.

Two findings changed the shape of the answer rather than fixing an arithmetic slip:

- **The anytime gap was comparing two different things.** `best_weight` came from whatever depth had confirmed something, and `bound` describes what could pass *every* tier. Subtracting one from the other produced a **negative gap** whenever the deep tier refuted what the screen had accepted. The gap is now measured against a full-depth best, so "nothing confirmed at depth yet" reads as a full gap instead of as a suspiciously small one.
- **The bound ignored stacks**, so on a stacked repository it named sets that could never land, `optimal` could never become true however much was validated, and `pending` priced candidates nobody could run.

And one that the seam table had not covered, which is the finding that would have cost the most:

> **The published cost interface would have been burned by #17 within a release or two.** `observe(tier, subset, seconds: float)`, a public `observations: Dict[str, List[Tuple[int, float]]]`, and `cost_from_log(tier: str)` all hard-code "one scalar per evaluation" — and merging publishes them to PyPI. Seam 2 is the `CostModel` *protocol*, and `observations` was not in the protocol; it was a public attribute that got exported. Worse, `runtime_checkable` only checks method presence, so a third-party model would keep passing `isinstance` while breaking at the call site.

The fix is cheap and was made before merge: `observations` is now private and the evidence is published through `summary()` (a dict, which can gain keys), and `observe` accepts `float | Mapping[str, float]` so per-stage durations land as **data** rather than as a signature change. **A seam table protects the boundaries it names; a public attribute beside one is still a published interface.**

Two mutations also survived the first pass — the tests named after "a tier that did not run is not a tier that passed" and after the constrained-maximality fix both stayed green when the property was deleted. Both were corrected rather than relabelled. Writing a test named after a regression is not the same as gating it.

## Consequences

- The expensive tier becomes affordable without becoming optional. It runs a handful of times instead of never.
- Every claim carries the tier it was validated at. Reports gain a true statement and lose the ability to make a false one.
- Two evaluation logs per two-tier run instead of one. A tiered run does *not* reuse an existing untiered log, because the log key now carries the tier name — the first tiered run on a repository re-screens. This is a real cost, accepted: a shared key would be exactly the cache collision the design exists to prevent.
- Cost estimates improve monotonically with use, and say when they are guesses.
- Each deep tier now spends one evaluation on its own base check, and the budget reserves it. That is the most expensive single run of the tier, and it is the one that must not be skipped: without it "nothing passes `e2e`" is reported as a finding.
- Change weights must be non-negative. The bound is the complement of the cheapest minimal hitting set, and that enumeration is best-first over cumulative weight — Dijkstra, which is wrong with negative edges, silently and in the dangerous direction. A negative weight is now refused rather than producing a bound below the true optimum labelled `provably maximal`.
- Nothing about the untiered path changes. `analyze()` is untouched; `analyze_tiered()` composes it.

## Seams (architecture-first turn-1 table)

| # | Seam | v1 default — no new dependency, not a stub | Replacement I can point at |
|---|---|---|---|
| 1 | validation tiers | `[Tier('validate', <today's validator>)]` — one tier reproduces current behaviour exactly | `staged_validation` / `js_validation` in `validation.py`; the e2e tier in the current scope |
| 2 | cost model | `MeasuredCost` fitted to the evaluation log's recorded durations, backed by declared per-tier costs | the `CostModel` protocol; a learned model in the style of [15] |
| 3 | tier availability | `available=None`, i.e. always — the truth for a unit-test tier | a `docker info` probe for the e2e tier |

```
NOT seams: the Tier record's shape, the JSONL row, the report wording, the log key format
           — written directly, on purpose.
Surface for v1: library only. CLI/MCP/HTTP/frontend/skills: questions answered, not built.
```

**Surfaces, asked not built.** *CLI:* a repeatable `--tier 'name:command[:cost]'` alongside the existing `--validate-stage` is the natural spelling, and asking the question found a real defect rather than confirming a guess — see below. It is tracked as its own change (#20) rather than smuggled into this one, because the tiered path also wants `--confirm-budget-seconds` and `--must-include`, and that is a CLI design rather than a flag. *MCP:* `analyze_tiered` takes flat arguments and returns a JSON-able result; no core change. *HTTP:* the deep tier's wall-clock exceeds any sane request timeout, so the run would have to become a job — a real change, and a reason not to build it now. *Skills / frontend:* nothing owed yet.

**What the CLI question actually found.** Writing out what an adapter would pass surfaced that `analyze_tiered` accepted `log_path` and then *silently discarded* it: the screen tier's log is handed to `analyze` explicitly, so the argument had no effect and said nothing. One path cannot hold several tiers without collapsing them into the shared cache entry this whole design exists to prevent, so `log_path` now refuses alongside `validate` and `log`, and points at `artifacts=` — the storage seam, which routes every tier's log through one store. That is the audit paying for itself before the surface was built, which is the point of asking.

**One-command test (the v1 definition of done):** `tests/test_tiers.py::test_tiers_keep_separate_logs_so_a_cheap_pass_answers_no_deep_question` runs the whole path against a real git repository with two real tiers, and asserts the screen and the deep tier disagree about the same set and that the disagreement survives to the answer. It must keep passing after any later seam swap.

## Rejected alternatives

**A `relevant_to` field declaring which changes a tier is about.** It would make a heavy tier cheap by never running it on sets that contain none of "its" changes. It is unsound in exactly the shape of the #9 decomposition bug (ADR-0019): an end-to-end tier is a whole-application test and can fail on an interaction between two changes that have nothing to do with it. Zero seams is a fine answer, and this is one of them. It could return as an explicitly-declared assumption, labelled the way `component_local` is (ADR-0019), if and only if someone has a validator for which it is genuinely true.

**Per-tier verdicts stored as a `tier` field on `Evaluation`.** One log with a tier column reads more elegantly and would let the closure reason across tiers. It changes the on-disk format, the closure semantics and `base.py` — a wide blast radius for a design that has not been used in anger yet. One log per tier gets the same soundness with an additive change. Revisit after the design has survived a real run.

**Expected-value scheduling (ProbDD [8], adaptive submodularity [17], sequential diagnosis [22]).** Order the deep evaluations by expected information per second rather than by weight per second, with a per-tier failure probability in the cost model. This is the right next step and the literature is ready for it. It is not v1: the frontier has about four members, so the ordering barely matters, and a probability model with four data points is decoration. Named here so the next person does not have to rediscover it.

**Pricing merges.** Measured at 0.21–0.69 s against 27–51 s of validation. The cost model prices tiers and changes, not merges.

## What this depends on and does not yet have

**Per-stage durations are not recorded, and this is the gap the whole cost model rests on.** `ValidationOutcome` persists one blended `duration`. `staged_validation` computes each stage separately — that is its entire purpose — and the log then discards the breakdown. So the regime is **latent**: this design infers "that was the cold one" from the size-0 point, which works only because the base check happens to be both the first evaluation and the only size-0 one. Record `setup.skipped` and the regime is **observed** instead — and so is the assumption this design currently has to make, that no *other* evaluation ever pays cold, which stops being true the moment a lockfile moves mid-run. The body's own 27.2–37.2 s spread may well be the same two regimes one level down, read as within-regime variance for want of the field that would say. Tracked as **i2mint/mergeset#17**; it is a change to `validation.py` and `base.py` and is deliberately not in this branch.

**Spend must be read from the log, not from the search state.** `Analysis.evaluations` counts what *this process* ran, so a re-run against a complete log reports zero spend for work that really happened (**i2mint/mergeset#16**). Everything here counts evaluations as rows in the tier's log.

**Flakiness is unmodelled.** `flake_tolerant` remains the cheap mitigation and `monotonicity_violations()` the honest report. A per-tier failure probability belongs with the expected-value scheduling above.

## References

1. Reiter R. **A theory of diagnosis from first principles.** Artificial Intelligence. 1987;32(1):57–95. — the hitting-set duality the solver rests on.
2. Liffiton MH, Sakallah KA. **Algorithms for computing minimal unsatisfiable subsets of constraints.** Journal of Automated Reasoning. 2008;40(1):1–33. — CAMUS.
3. Liffiton MH, Previti A, Malik A, Marques-Silva J. **Fast, flexible MUS enumeration.** Constraints. 2016;21(2):223–250. [PDF](https://sun.iwu.edu/~mliffito/publications/constraints_liffiton_marco.pdf) · [code](https://github.com/liffiton/MARCO)
4. Marques-Silva J, Janota M, Belov A. **Minimal sets over monotone predicates in Boolean formulae.** CAV 2013. [PDF](https://sat.inesc-id.pt/~mikolas/cav13.pdf)
5. Janota M, Marques-Silva J. **On the query complexity of selecting minimal sets for monotone predicates.** Artificial Intelligence. 2016;233:73–83. [link](https://www.sciencedirect.com/science/article/pii/S0004370216000035)
6. Junker U. **QUICKXPLAIN: preferred explanations and relaxations for over-constrained problems.** AAAI 2004.
7. Zeller A, Hildebrandt R. **Simplifying and isolating failure-inducing input.** IEEE Transactions on Software Engineering. 2002;28(2):183–200.
8. Wang G, Shen R, Chen J, Xiong Y, Zhang L. **Probabilistic delta debugging.** ESEC/FSE 2021. [PDF](https://xiongyingfei.github.io/papers/FSE21a.pdf) · [code](https://github.com/Amocy-Wang/ProbDD)
9. Bendík J, Beneš N, Černá I, Barnat J. **Tunable online MUS/MSS enumeration.** arXiv:1606.03289. [PDF](https://arxiv.org/pdf/1606.03289)
10. Marques-Silva J, Heras F, Janota M, Previti A, Belov A. **On computing minimal correction subsets.** IJCAI 2013. [PDF](https://www.ijcai.org/Proceedings/13/Papers/098.pdf)
11. Brun Y, Holmes R, Ernst MD, Notkin D. **Proactive detection of collaboration conflicts.** ESEC/FSE 2011. [PDF](https://www.cs.ubc.ca/~rtholmes/papers/fse_2011_brun.pdf)
12. Brun Y, Holmes R, Ernst MD, Notkin D. **Early detection of collaboration conflicts and risks.** IEEE Transactions on Software Engineering. 2013;39(10):1358–1375. [abstract](https://homes.cs.washington.edu/~mernst/pubs/vc-conflicts-tse2013-abstract.html)
13. Walcott KR, Soffa ML, Kapfhammer GM, Roos RS. **Time-aware test suite prioritization.** ISSTA 2006. [PDF](https://www.cs.virginia.edu/~soffa/Soffa_Pubs_all/Conferences/Time-Aware.Walcott.2006.pdf)
14. Zhang L, Hou S-S, Guo C, Xie T, Mei H. **Time-aware test-case prioritization using integer linear programming.** ISSTA 2009. [link](https://dl.acm.org/doi/10.1145/1572272.1572297)
15. Machalica M, Samylkin A, Porth M, Chandra S. **Predictive test selection.** ICSE-SEIP 2019; arXiv:1810.05286. [PDF](https://arxiv.org/pdf/1810.05286)
16. Beheshtian MJ, Bezemer C-P, et al. **Software batch testing to save build test resources and to reduce feedback time.** IEEE Transactions on Software Engineering. 2022;48(8). [link](https://ieeexplore.ieee.org/document/9392370/)
17. Golovin D, Krause A. **Adaptive submodularity: theory and applications in active learning and stochastic optimization.** Journal of Artificial Intelligence Research. 2011;42:427–486. [arXiv](https://arxiv.org/abs/1003.3967)
18. Deshpande A, Hellerstein L, Kletenik D. **Approximation algorithms for stochastic Boolean function evaluation and stochastic submodular set cover.** arXiv:1303.0726. [arXiv](https://arxiv.org/abs/1303.0726)
19. Ünlüyurt T. **Sequential testing of complex systems: a review.** Discrete Applied Mathematics. 2004;142(1–3):189–205.
20. Zilberstein S. **Using anytime algorithms in intelligent systems.** AI Magazine. 1996;17(3):73–83.
21. Zilberstein S, Russell S. **Optimal composition of real-time systems.** Artificial Intelligence. 1996;82(1–2):181–213. [PDF](https://people.eecs.berkeley.edu/~russell/papers/aij-anytime.pdf)
22. de Kleer J, Williams BC. **Diagnosing multiple faults.** Artificial Intelligence. 1987;32(1):97–130.
23. Mergify. **Merge queue batches.** [docs](https://docs.mergify.com/merge-queue/batches/) — the industrial state of the art: batch, bisect on failure, and reuse the parent batch's passing results.
