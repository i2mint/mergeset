---
adr: 0032
title: "A validator's fingerprint covers the files outside the repository it is told it runs"
status: accepted
---

# 0032 — A validator's fingerprint covers the files outside the repository it is told it runs

ADR 0029 pinned each row to a fingerprint of what the validator runs, and "what it runs" is the command's text: the digest covers the command, stages, timeout, environment and retries. A command such as `python /elsewhere/check.py` keeps its fingerprint when `check.py` is edited, so the old script's verdicts answered the new one (i2mint/mergeset#39). Files inside the analysed repository were never the problem: ADR 0028 pins them through the commits.

**Decision.** Every shipped validator that runs something (`command_validation`, `pytest_validation`, `act_validation`, `staged_validation`) takes `inputs=[paths]`, and the CLI takes `--validate-input PATH` (repeatable, applied to every validator the run builds, every tier included). `mergeset.validation.inputs_digest` digests each path's contents when the validator is made, and the digest joins the fingerprint: a file by its bytes, a directory by every file under it (relative names and contents), a missing path as `missing`, so creating it later counts as a change. Paths are made absolute against the current directory, not the worktree, and spellings of one path count once. An empty `inputs` digests exactly like before the option existed, so upgrading retires no row. `flake_tolerant` digests the fingerprint it wraps, so the inputs carry through.

**Declared, not guessed.** Scanning the command for paths would hash `/usr/bin/python` and miss a script the command finds by itself (`make check` running `~/checks/x.sh`). Only the user knows which outside files change a verdict, so they name them. A `--validate-input` that does not apply to a tier (a tier that does not run the file) costs that tier one re-run when the file changes, never a wrong answer.

**Read once.** The contents are read when the validator is made, at the start of a CLI run. A file edited while a run is going is seen by the next run, not by the one in progress. `--validate-input` with `--merge-only` and no tier is refused: merge-only runs nothing, so the files would be read and ignored.
