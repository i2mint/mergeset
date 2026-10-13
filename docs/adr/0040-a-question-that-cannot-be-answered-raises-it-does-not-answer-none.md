---
adr: 0040
title: "A constrained search that cannot run raises; it does not answer None"
status: accepted
---

# 0040 — A constrained search that cannot run raises; it does not answer None

`best_set_including` (`--must-include`) returns `(best or None, conflicts, spent)`, and `None` means "no set keeps these: every way of resolving the known conflicts drops one". An `ERROR` evaluation inside it returned `None` as well, so a resolver timeout read as the finding "no validated set keeps X"; inside a conflict shrink it counted as "not bad" and could record a wrong conflict (i2mint/mergeset#54, found by the review of #52). ADR 0017 and 0036 give the rule: could-not-run is not a result.

**Decision.** The function has no room in its return value to say "unfinished", so it raises `EvaluationAborted(why, conflicts)` (new, a `MergesetError`, exported) on any `ERROR`, from the search and from the shrink alike; `conflicts` are the sound ones established before it. `analyze_tiered` catches it: the maximal sets stand, `best_including` is `None`, the note says `--must-include was not answered: <why>`, an erroring search is appended to `analysis.searches` so `Analysis.aborted` is set (ADR 0038: the report headlines it and the CLI exits 3), and the abort is reported as a *phase* after the tiers (`Analysis.aborted_phase = "--must-include"`, not a tier: the header says `ABORTED during --must-include`, the plans are not disowned, and integration branches are still made). The exception also carries `best_so_far`, a set that passed before the abort (the grow step's ERROR must not lose the candidate that had just passed), reported as a validated set that keeps what was asked but may not be the heaviest. The first version put the phase in the tier slot; review showed that told the reader that confirmed plans were unconfirmed. A library caller of `best_set_including` that treated `None` as an answer to an erroring oracle now gets an exception instead of a wrong answer.
