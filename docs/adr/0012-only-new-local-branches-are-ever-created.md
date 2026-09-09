---
adr: 0012
decision: D12   # the identifier this was published under before the split
title: "Only *new* local branches are ever created"
status: accepted
---

# 0012 — Only *new* local branches are ever created

`create_integration_branch` refuses to touch a branch that already exists unless explicitly forced, and nothing in the package pushes. This is a hard safety boundary, not a default: the tool is pointed at repositories where existing branches are other people's in-flight work.
