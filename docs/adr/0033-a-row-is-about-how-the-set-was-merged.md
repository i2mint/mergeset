---
adr: 0033
title: "A row is about how the set was merged, where that decided its outcome"
status: accepted
---

# 0033 — A row is about how the set was merged, where that decided its outcome

ADR 0029 pinned rows to the validator and said: "How a set was *merged* is not part of the key: a PASS reached through an assisted resolution is reused by a run without the resolver." That reuse is wrong (i2mint/mergeset#34). A set that merges only with `--resolver claude` records an assisted PASS, and a later run of the same log with `--resolver none` reused it, although without the resolver the set is a textual conflict. The reverse reused a conflict FAIL where the resolver would have merged.

**Decision.** Every row records `resolver`: `none` when conflicts were left standing, the resolver's fingerprint otherwise (`mergeset.oracle.resolver_fingerprint_of`; `claude_code_resolver` digests its policy, command and timeout; a resolver that cannot say records `unknown`, which matches only other `unknown` rows, and its author can set `resolver.resolver_fingerprint`). `EvaluationLog.pin(resolver=)` scopes a log to one; `analyze` pins to its resolver, and every deeper tier pins to the screen's, since a deep tier merges with the screen's recorded resolutions (ADR 0031).

**Only rows the resolver decided are pinned** (`Evaluation.merge_dependent`): an assisted merge, which exists only because a resolver resolved it, and a textual conflict, which stands only because none did. A clean merge is the same tree whatever the resolver, so its PASS or FAIL answers every run; pinning it too would re-run every validation whenever `--resolver` is toggled. A conflict answers a run with no resolver whoever recorded it: no resolver merges nothing a resolver could not. An assisted row, or a conflict a resolver declined, answers only runs with the same resolver fingerprint.

**Rows from another resolver are kept,** listed by `stale` and by `other_resolver`, and the analysis note counts them. **Old rows** (written before this record, no `resolver`) that are merge-dependent are *unpinned*: not trusted by default, adopted with `trust_unpinned`; an old conflict still answers a run without a resolver. Old clean rows are unaffected, so upgrading re-runs only the merges a resolver decided, which cost a merge, not a validation, except for assisted sets.

**Even trusted, an old row cannot contradict what is known without it.** A run with no resolver needs no row to say who resolved it: a conflict stands without a resolver and an assisted merge cannot happen without one, so `trust_unpinned` never adopts an old assisted PASS into such a run. Timings of rows another resolver decided do not price a tier either (an assisted row's time includes the resolver's).
