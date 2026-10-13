---
adr: 0035
title: "An input file is trusted by its stat once its last change is old"
status: accepted
---

# 0035 — An input file is trusted by its stat once its last change is old

ADR 0032 digests the contents of every `--validate-input` when a validator is made, and again before and after every evaluation, to refuse a verdict reached across an edit. A run read every input once per tier, once for a default validator no tier ran, and twice per evaluation; a virtual environment named as an input (8.7 GB) took about 36 s per read (i2mint/mergeset#42).

**Decision.** `inputs_digest` keeps each file's content digest in `FILE_DIGESTS`, keyed by real path, device, inode, size, mtime and ctime, and reuses it while all of them match. A digest is kept only when the file's last change (the later of mtime and ctime) is `RACY_SECONDS` (2 s) older than the read that produced it, which is git's racy-clean rule: an edit after the read stamps a later time, so it cannot leave the key unchanged, and a same-size edit within one timestamp tick of the read is always read again. ctime is in the key because tools that set mtime back (`touch -d`, archive extraction) cannot set ctime back on local filesystems. The CLI also builds the bare validator only when a bare tier (or an untiered run) uses it. Measured: 35.8 s for the first read of that venv, 2.0 s for each later one.

**Accepted blind spots,** the same as `make`'s and git's: a second write through a shared `mmap` to a page that is already dirty changes no timestamp; a network filesystem may serve cached attributes (NFS, for up to a minute), stamp times from a clock behind this one, or derive ctime from mtime (vfat, sshfs). An input edited that way mid-run can slip past the check around each evaluation. `inputs_digest(cache=None)` reads every file, and `mergeset.validation.FILE_DIGESTS = None` turns the cache off for every validator; the cache is bounded (`MAX_CACHED_DIGESTS`) and lives for the process.

**Considered: no cache for the checks around each evaluation.** Those are two of the reads per evaluation, so they are most of the cost the issue is about; dropping the cache there would keep the minutes the issue reports.
