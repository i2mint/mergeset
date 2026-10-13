---
adr: 0036
title: "A resolver that raises did not run the experiment"
status: accepted
reverses: the last sentence of ADR 0031's second paragraph (a resolver that raises has declined)
---

# 0036 — A resolver that raises did not run the experiment

`_try_assisted` caught every exception from the resolver and treated it as a decline: a merge-stage `FAIL` row, pinned to the resolver's fingerprint. A timeout is not a statement about the conflict, yet the next run, with the same healthy resolver, found that row, reused it, made no call, and kept the pair excluded for good (i2mint/mergeset#48). Since #44 a `--resolver` reaches this code by default.

**Decision.** A resolver that raises produces an `ERROR` evaluation (`MergeOutcome.reason == "error"`, ADR 0017), whose note names the exception type and message. An `ERROR` row is never reused (`EvaluationLog.exact` answers only `PASS` and `FAIL`), so the next run asks the resolver again. A resolver that *returns* `False`, or a resolution that `_vouches_for` refuses, is still a decline and still a `FAIL`: the resolver looked at the conflict and gave an answer.

**One ERROR stops every search.** ADR 0017 stops the search that met the `ERROR`; since the same call would fail again, nothing after it may ask either. `find_maximal_good_sets` ends on an `ERROR` wherever it meets one, including inside conflict shrinking (it used to count as "not bad" and record a wrong conflict); `analyze` does not start the next component's search or the global verification; `analyze_tiered` skips the deeper tiers and `must_include`. Found by the review of the PR that introduced this record: without it a 300 s timeout was paid again by each of those phases.

**Consequence, accepted.** ADR 0017 makes the first `ERROR` abort the search, so a timeout now stops the run with `aborted: the conflict resolver raised TimeoutError: ...` instead of recording a conflict and carrying on. That was the reason the old code swallowed it ("an ERROR would abort the whole search over one slow call"); but a search that carries on past an unrunnable experiment reports a mergeable set smaller than the truth, with confidence. Everything decided before the abort is in the log, so the rerun resumes where it stopped and spends only the evaluations that remain.
