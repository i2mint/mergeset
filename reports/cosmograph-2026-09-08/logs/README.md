# Raw validation output, one file per evaluation

Full `pnpm install` / `build:cosmos` / `vitest` / `eslint` output for each of the 16 evaluations in `../evaluations.jsonl`. The filename is the evaluation's label: `s` followed by the PR numbers in the set.

These are force-added past the repository's `*.log` ignore rule, deliberately: `evaluations.jsonl` records that a set failed and which tests failed, and these files are the evidence behind that. Absolute local paths have been replaced with placeholders (`<clone>`, `<eval-worktree>`, `$PP`, `~`), so line content is verbatim but path prefixes are not.
