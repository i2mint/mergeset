# Architecture decision records

> **A note on the trial run.** These decisions were made while analysing a real
> repository with 15 open pull requests. That repository is **private**, so its
> pull requests appear here as `PR-01`…`PR-17` and its identifiers are described
> rather than named. The reasoning is unchanged; only the labels are. Derived
> artifacts from that run — reports, logs, fixtures — are not in this repository
> at all, and must not be: see the `app-data-lifecycle` skill, "provenance
> outranks everything".


Every non-obvious choice, with the reason. Entries are append-only; when a decision is reversed, the old entry stays and the new one says what changed.

One decision per file. The `decision:` field in each file's front matter carries the
`D<n>` identifier the record was published under before the split, so older references
(commit messages, issues, `HANDOFF` notes) still resolve.

| ADR | was | decision |
|---|---|---|
| [0001](0001-the-name-is-mergeset.md) | `D1` | The name is `mergeset` |
| [0002](0002-the-unit-is-a-change-not-a-branch-or-a-pr.md) | `D2` | The unit is a **change**, not a branch or a PR |
| [0003](0003-the-cli-adapter-is-cw-not-argh.md) | `D3` | The CLI adapter is `cw`, not `argh` |
| [0004](0004-the-evaluation-log-is-the-single-source-of-truth-and-it-is-a.md) | `D4` | The evaluation log is the single source of truth, and it is append-only JSONL |
| [0005](0005-monotonicity-is-a-prior-not-an-invariant-and-violations-are.md) | `D5` | Monotonicity is a prior, not an invariant, and violations are reported rather than smoothed over |
| [0006](0006-cost-ordering-is-the-architecture.md) | `D6` | Cost ordering is the architecture |
| [0007](0007-file-overlap-decomposition-is-an-assumption-and-it-is-opt-ou.md) | `D7` | File-overlap decomposition is an assumption, and it is opt-out |
| [0008](0008-assisted-merges-are-always-flagged-never-silently-clean.md) | `D8` | Assisted merges are always flagged, never silently clean |
| [0009](0009-weights-mean-cost-of-dropping-this-change.md) | `D9` | Weights mean "cost of dropping this change" |
| [0010](0010-the-oracle-returns-a-record-not-a-bit.md) | `D10` | The oracle returns a record, not a bit |
| [0011](0011-merge-order-is-deterministic-and-recorded.md) | `D11` | Merge order is deterministic and recorded |
| [0012](0012-only-new-local-branches-are-ever-created.md) | `D12` | Only *new* local branches are ever created |
| [0013](0013-git-merge-tree-is-always-chained-through-base.md) | `D13` | `git merge-tree` is always chained through base *(found by TEST)* |
| [0014](0014-validation-is-an-ordered-sequence-of-named-stages.md) | `D14` | Validation is an ordered sequence of named stages *(found by TEST)* |
| [0015](0015-stacks-are-a-forest-and-the-constraint-lives-in-the-core.md) | `D15` | Stacks are a forest, and the constraint lives in the core *(found by TEST)* |
| [0016](0016-a-forge-s-ci-verdict-is-only-trusted-when-the-bases-agree.md) | `D16` | A forge's CI verdict is only trusted when the bases agree *(found by TEST)* |
| [0017](0017-could-not-run-the-experiment-is-not-the-experiment-failed.md) | `D17` | "Could not run the experiment" is not "the experiment failed" *(found by TEST)* |
| [0018](0018-the-base-is-evaluated-before-anything-else.md) | `D18` | The base is evaluated before anything else |
| [0019](0019-file-overlap-components-are-a-search-strategy-not-a-soundnes.md) | `D19` | File-overlap components are a search strategy, not a soundness claim *(found by TEST)* |
| [0020](0020-the-oracle-s-failure-output-attributes-blame.md) | `D20` | The oracle's failure output attributes blame *(found by TEST)* |
| [0021](0021-an-empty-log-is-still-a-log.md) | `D21` | An empty log is still a log |
| [0022](0022-the-cli-can-describe-a-real-project-not-only-an-easy-one.md) | `D22` | The CLI can describe a real project, not only an easy one *(found by TEST)* |
| [0023](0023-a-refusal-is-a-result-not-a-traceback.md) | `D23` | A refusal is a result, not a traceback |
| [0024](0024-nothing-is-reported-twice-under-two-explanations.md) | `D24` | Nothing is reported twice under two explanations *(found by TEST)* |
| [0025](0025-nothing-is-recommended-that-was-never-evaluated-as-a-whole.md) | `D25` | Nothing is recommended that was never evaluated as a whole |

25 records. Append-only: when a decision is reversed, the old record stays
and the new one says what changed.
