---
adr: 0038
title: "An aborted run says so, and exits 3"
status: accepted
---

# 0038 — An aborted run says so, and exits 3

ADR 0017 and 0036 make an `ERROR` end the search. The report did not know: it headlined "partial (budget reached)", explained an empty result as a budget stop, showed the `ERROR` row's detail as `conflict: <files>` (hiding the exception) and said "every row is re-usable", and the CLI exited 0. A script, or a person skimming, read an unfinished run as a finished one (i2mint/mergeset#53).

**Decision.** `Analysis.aborted` (the first search's error, or `None`) is the one fact. The Markdown and HTML reports headline `ABORTED`, open with a banner carrying the reason and saying the plans are only what was established before it, and no longer call an empty conflict list "a budget stop". An `error` row in the log table shows its note, and the table says such rows are asked again. The CLI returns the report as `AbortedReport` (a `str`), whose egress exits `EXIT_ABORTED` (3; 1 and 2 stay with Python and argparse), and does not create integration branches from an aborted run. The report is still printed in full: it is what was established.

Refusals (`mergeset cannot run yet`, `refused to run`) keep exit 0 as before; that is a separate question.
