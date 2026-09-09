---
adr: 0023
decision: D23   # the identifier this was published under before the split
title: "A refusal is a result, not a traceback"
status: accepted
---

# 0023 — A refusal is a result, not a traceback

`MergesetError` escaped the CLI as a stack trace with the reason at the bottom. It is now caught and rendered like any other outcome, and the detail is the most specific thing available: failing test ids when the runner named some, otherwise the exit code and the last lines of what it printed — because "exit 1 and nothing else" is exactly the case where a bare verdict leaves the user with nowhere to look.
