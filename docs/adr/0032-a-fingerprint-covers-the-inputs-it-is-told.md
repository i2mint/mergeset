---
adr: 0032
title: "A validator's fingerprint covers the files outside the repository it is told it runs"
status: accepted
---

# 0032 — A validator's fingerprint covers the files outside the repository it is told it runs

ADR 0029 pinned each row to a fingerprint of what the validator runs, and "what it runs" is the command's text: the digest covers the command, stages, timeout, environment and retries. A command such as `python /elsewhere/check.py` keeps its fingerprint when `check.py` is edited, so the old script's verdicts answered the new one (i2mint/mergeset#39). Files inside the analysed repository were never the problem: ADR 0028 pins them through the commits.

**Decision.** Every shipped validator that runs something (`command_validation`, `pytest_validation`, `act_validation`, `staged_validation`, `js_validation`) takes `inputs=[paths]`, and the CLI takes `--validate-input PATH` (repeatable, applied to every validator the run builds, every tier included). `mergeset.validation.inputs_digest` digests each path's contents when the validator is made, and the digest joins the fingerprint: a file by its bytes, a directory by every file under it (relative names and contents), a missing path as `missing`, so creating it later counts as a change. Relative paths are resolved against the current directory, not the worktree. An empty `inputs` digests exactly like before the option existed, so upgrading retires no row. `flake_tolerant` digests the fingerprint it wraps, so the inputs carry through.

**Declared, not guessed.** Scanning the command for paths would hash `/usr/bin/python` and miss a script the command finds by itself (`make check` running `~/checks/x.sh`). Only the user knows which outside files change a verdict, so they name them. A `--validate-input` that does not apply to a tier (a tier that does not run the file) costs that tier one re-run when the file changes, never a wrong answer.

**Read when made, held for the run.** The contents are digested when the validator is made, at the start of a CLI run, and checked again before and after every run of it. The command reads the files afresh each time, so a file edited mid-run would be judged by the new script and recorded under the old one's fingerprint, and reverting the edit later would let those rows answer the old script. Instead the run stops with a `CapabilityError` that names the changed files; the next run digests the new contents. The check costs one digest per evaluation, small next to the evaluation itself unless an input is a large directory.

**Spellings.** Paths are resolved to real paths (`~`, relative paths, symlinks), a directory is walked following symlinks and visiting each real directory once, a file that cannot be read digests as `unreadable`, and a lone string is refused rather than read one character at a time. On the CLI, a `--validate-input` that does not exist is refused: the flag takes every value after it, so it is most often a branch typed in the wrong place. `--validate-input` with `--merge-only` and no tier is refused too: merge-only runs nothing, so the files would be read and ignored. `pytest_validation(select_paths=...)` has no fingerprint, so passing it `inputs` is refused rather than ignored.
