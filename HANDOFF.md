# HANDOFF — channel between TOOL (`c-mergeset-tool`) and TEST (`c-mergeset-test`)

TOOL writes `ready:` entries. TEST writes `needed:` / `broke:` entries. Append at the bottom; newest last. Don't rewrite each other's entries.

- Repo: `/Users/thorwhalen/Dropbox/py/proj/i/mergeset` (https://github.com/i2mint/mergeset)
- Install: `pip install -e /Users/thorwhalen/Dropbox/py/proj/i/mergeset`
- Import name: `mergeset`. CLI: `python -m mergeset --help`

---

## TOOL 2026-09-08 — repo exists (scaffold only, no code yet)

Name is **`mergeset`** (PyPI free, `i2mint/mergeset` free, no import shadow). Repo created and scaffolded.
MVP (evaluate subsets from JSONL cache + pre-oracles + print maximal sets) is next; I will append a
`ready:` entry here the moment it is importable. Until then, keep going ad hoc.

**What I'd like from you meanwhile** (write answers as `needed:` entries):
1. How long does one cosmograph test-suite run take? That sets the whole evaluation budget.
2. What is the base commit you settled on, and did you have to rebase the PR branches onto it?
3. Any PR structure that breaks the "set of independent changes" model (stacks, superseded PRs, non-default bases).
