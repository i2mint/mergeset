---
adr: 0029
title: "A log row is about what was run too, not only about the commits"
status: accepted
---

# 0029 — A log row is about what was run too, not only about the commits

ADR 0028 pinned rows to commits and left the validator out of the key: "a changed validation command under one log is still the user's to notice." Tiers made that common rather than rare. A tier's log is keyed by repository and tier name, and a tier is the thing people tune, so `--tier u:true` followed by `--tier u:false` reused the first run's passes as answers to the second (i2mint/mergeset#32). The untiered log did the same when `--validate-command` changed.

**Decision.** A validator may say what it runs: a `validator_fingerprint` attribute, read by `mergeset.validation.fingerprint_of`. Every shipped validator sets one, `kind:` followed by a digest of what can change a verdict: the command or pytest arguments, the stages (name, command, timeout, required), the timeout, the environment, and the retries of `flake_tolerant`. A stage's own `fingerprint` (which skips a setup that already ran in a worktree) is left out, since it does not change the verdict. Every `Evaluation` row records the fingerprint of the validator that judged it, and `EvaluationLog.pinned(validator=)` scopes a log to one: `analyze` pins to its validator, `analyze_tiered` pins each tier's log to that tier's validator.

**Rows judged by another validator are kept,** like rows about other commits: they are listed by `stale` (and by `other_validator`), not counted, and the analysis note says how many were judged by a different validator. `show-log` warns when rows mix validators.

**Old rows.** Rows written before this record no validator. They load, are listed by `unpinned`, and are not trusted by default: they may have been judged by a command that has since changed. `trust_unpinned` / `--trust-unpinned-log` adopts them, as it adopts rows from before ADR 0028. A row that *records* a different validator is never adopted.

**A validator that cannot say what it runs** (a user callable, or `pytest_validation` with a `select_paths` callable) has no fingerprint, and then rows match on commits alone, as before. A callable's name says nothing about what it selects or checks, so no fingerprint is guessed from it. Its author can set `validate.validator_fingerprint = 'smoke-v2'` and bump it when the check changes.

**Why per row, not per file.** Putting the fingerprint in the log's file name would also stop the reuse, but it would throw away the tier's timing history (the cost model learns from every row of a tier's log, ADR 0026) and leave old files orphaned rather than reported. Per-row pinning keeps one log per tier and reuses the machinery of ADR 0028.
