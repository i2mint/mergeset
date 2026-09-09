---
adr: 0003
decision: D3   # the identifier this was published under before the split
title: "The CLI adapter is `cw`, not `argh`"
status: accepted
---

# 0003 — The CLI adapter is `cw`, not `argh`

The spec asked for `argh`. `argh` is LGPL-3.0-or-later and is being removed fleet-wide (per the `python-dispatching` skill), so this package uses `cw`, which is MIT with zero runtime dependencies. The durable part is `mergeset/cli.py::_dispatch_funcs` — an SSOT list of plain functions — and only the last line binds it to an adapter, so this decision costs one line to reverse and the same list is what a future HTTP or MCP surface would consume.
