---
adr: 0006
decision: D6   # the identifier this was published under before the split
title: "Cost ordering is the architecture"
status: accepted
---

# 0006 — Cost ordering is the architecture

The pipeline is ordered by price, and nothing expensive runs until everything cheap has had its say:

1. **free** — a change whose own CI is already red against its base is a conflict of size one;
2. **milliseconds** — pairwise `git merge-tree --write-tree` finds textual conflicts with no worktree and no checkout (this is why git >= 2.38 is a hard requirement, checked up front with a fixable error message);
3. **milliseconds** — file-overlap connected components split one `2**n` search into several small independent ones, whose answers combine by Cartesian product;
4. **minutes each** — only then the real merge-and-test oracle.

Each of 1–3 can be switched off by one keyword, because each embeds an assumption (see D7) that may not hold for a given repository.
