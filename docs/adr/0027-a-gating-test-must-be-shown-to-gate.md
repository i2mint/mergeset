---
adr: 0027
title: "A gating test must be shown to gate, not merely named after the property"
status: accepted
---

# 0027 — A gating test must be shown to gate, not merely named after the property

Four times in this project's first two days, a test named after a property did not test it. Every one was green, and every one was found the same way: delete the production change, and see whether the test notices.

- `test_evaluation_log_never_defaults_inside_the_analysed_repo` was labelled "the regression this whole module exists for". It exercised the helper. Revert the change in `analyze()` and it still passed.
- One assertion read `default.endswith(os.path.join("", "mergeset")) or default.endswith("mergeset")`. `os.path.join("", "mergeset")` *is* `"mergeset"`; both branches of the `or` were the same expression.
- `test_slugified_names_do_not_escape_the_store` asserted `".." not in key`, which the implementation never guaranteed. It passed because of the three inputs chosen.
- Two mutation checks written *for the tiered work* were themselves decoration — green with the property deleted.

The pattern is not carelessness. A test written immediately after a fix passes for two reasons at once — the fix works, and the test is aimed at it — and those are indistinguishable while the fix is present. The name then records the intent, and the intent is what later readers trust.

The **name** is what turns a gap into damage. A missing test costs vigilance: nobody is relying on it. A *misnamed passing* one spends that vigilance — the next person reads `test_evaluation_log_never_defaults_inside_the_analysed_repo` as a guarantee and deletes a safeguard on the strength of it. The worse the name is at describing what the test does, the more confidently it will be trusted.

Note which of the four reads as most rigorous: the assertion with two `or` branches. Two branches look like two cases considered.

## Decision

**A test that exists to gate a behaviour is not finished until it has been observed failing without that behaviour.** Concretely, before a gating test is committed:

1. Revert or mutate the production change it protects — one line is enough.
2. Run that test. **It must fail.**
3. Restore, and confirm it passes.
4. Say so in the commit message, so a reviewer knows the check was done rather than assumed.

This applies to regression tests and to any test asserting a safety property. It does not apply to ordinary example-based tests, where the assertion and the behaviour are the same thing.

**Before the commit, not before the merge.** That is the sub-rule that makes the rest stick. At the moment of writing, the fix is in your head and you know which line to revert; thirty seconds later it is done. All four failures above were caught later and more expensively — two by an adversarial reviewer, two by a mutation pass run only because a branch was about to publish. A review can catch these; it should not have to, and it will not catch them reliably, because from the outside a passing test named after a property is indistinguishable from one that holds it.

## Consequences

It costs about thirty seconds and it is the only thing that distinguishes a gate from a label. A green suite says the code does not contradict the tests; it says nothing about whether the tests would notice if it did. Coverage does not help — every one of the failures above ran the line it was supposed to be protecting.

The cheap generalisation, which is the same rule the redaction work arrived at from the other direction (see `app-data-lifecycle`, "grade the property, not the paths"): **verify the property, not the artifact that is supposed to embody it.** A passing test, a vanished file path and a rendered PDF are all artifacts. Whether the property holds is a separate question, and it is always the one being asked.
