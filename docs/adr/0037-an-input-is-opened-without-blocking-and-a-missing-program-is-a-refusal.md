---
adr: 0037
title: "An input is opened without blocking, and a missing program is a refusal"
status: accepted
---

# 0037 — An input is opened without blocking, and a missing program is a refusal

Found by the review of ADR 0035's change (i2mint/mergeset#51).

**Digests.** `inputs_digest` statted a path, saw a regular file, then `open`ed it. A FIFO swapped in between makes `open` wait for a writer that never comes, and the run hangs. The file is now opened with `O_NONBLOCK`, `fstat`ed, and read only if the opened handle is a regular file (anything else digests as `missing`, as a non-regular path always did). The cache key is the handle's own stat, so it names the bytes that were read rather than what the path was a moment before.

**A missing program.** When the validator's executable (the default `pytest`) is not on the `PATH` it runs with, `_run` raised an uncaught `FileNotFoundError`. It now raises `CapabilityError` naming the program and the fix, which the CLI already renders as "mergeset cannot run yet" (ADR 0023: a refusal is a result, not a traceback). It is not a `FAIL`: it says nothing about the changes (ADR 0017). A `FileNotFoundError` for any other reason (a vanished worktree) is still raised as it was.

**Smaller.** `--tier a b`, two bare names, is refused before the bare validator is built, so a refused run no longer pays for digesting its inputs twice. The `cache=` default prints as `FILE_DIGESTS` in `inputs_digest`'s signature.
