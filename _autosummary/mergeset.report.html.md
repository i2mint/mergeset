# mergeset.report

Rendering an [`Analysis`](mergeset.analysis.html.md#mergeset.analysis.Analysis) for humans.

Two renderers: a Markdown report meant to be read in a terminal or a PR comment,
and a single self-contained HTML file (no build step, no CDN) meant to be opened
and poked at. Both are pure functions of the analysis, which is itself derived
from the evaluation log — so a report can always be regenerated without
re-running anything expensive.

### Module Attributes

| [`REPORT_FORMATS`](#mergeset.report.REPORT_FORMATS)   | format name -> (key suffix, is it bytes).   |
|-------------------------------------------------------------------|---------------------------------------------|

### Functions

| [`html_report`](#mergeset.report.html_report)(analysis, \*[, title])                 | Render the analysis as one self-contained HTML file.                     |
|-----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`markdown_report`](#mergeset.report.markdown_report)(analysis, \*[, title])             | Render the analysis as Markdown.                                         |
| [`pdf_report`](#mergeset.report.pdf_report)(analysis, \*[, title])                  | Render the analysis as a PDF, for the reader who wants one file to keep. |
| [`stage_breakdown`](#mergeset.report.stage_breakdown)(record)                            | Where an evaluation's time went, stage by stage; `''` if not recorded.   |
| [`write_reports`](#mergeset.report.write_reports)(analysis, \*[, title, formats, ...]) | Render a run's reports into the artifact store; return `{format: key}`.  |

### mergeset.report.REPORT_FORMATS *= {'html': ('report.html', False), 'markdown': ('REPORT.md', False), 'pdf': ('report.pdf', True)}*

format name -> (key suffix, is it bytes).

* **Type:**
  What `write_reports` can produce

### mergeset.report.html_report(analysis, , title='mergeset')

Render the analysis as one self-contained HTML file.

No build step, no CDN, no network: a single file that can be opened from
disk or attached to an issue. It draws the conflict graph (nodes = changes,
edges = conflicts, textual vs validation distinguished), the maximal sets,
and the evaluation timeline.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.report.markdown_report(analysis, , title='mergeset report')

Render the analysis as Markdown.

Sections, in the order a reader actually wants them: what to merge, what
stops the rest, and only then the evidence.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.report.pdf_report(analysis, , title='mergeset report')

Render the analysis as a PDF, for the reader who wants one file to keep.

Rendered from the **Markdown**, not the HTML. The HTML report draws its
conflict graph and tables from an embedded JSON blob at load time, so a
print pipeline that does not execute JavaScript would render a blank page —
a PDF that looks fine until someone opens it. The Markdown is static, so
what is printed is what the report says.

Needs `pdfdol`; `pip install 'mergeset[pdf]'`. The error says so rather
than surfacing an ImportError from three frames down.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### mergeset.report.stage_breakdown(record)

Where an evaluation’s time went, stage by stage; `''` if not recorded.

The actionable version of a duration: “33 s of its 51 s installing
dependencies” says what to fix, “51 s” does not. The remainder of the
total – merging, worktree setup – is shown as `other`.

```pycon
>>> from mergeset.base import StageRun, ValidationOutcome, Verdict
>>> v = ValidationOutcome(True, duration=48.5, stages=[
...     StageRun('setup', 33.0, 0), StageRun('build', 9.0, 0),
...     StageRun('test', 6.5, 0)])
>>> stage_breakdown(Evaluation(frozenset('a'), Verdict.PASS,
...                            validation=v, duration=49.0))
'setup 33.0 · build 9.0 · test 6.5 · other 0.5'
>>> v = ValidationOutcome(True, stages=[StageRun('setup', skipped=True),
...                                     StageRun('test', 6.0, 0)])
>>> stage_breakdown(Evaluation(frozenset('a'), Verdict.PASS, validation=v,
...                            duration=6.0))
'setup skipped · test 6.0'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### mergeset.report.write_reports(analysis, , title='mergeset report', formats=('markdown', 'html'), key=None, reports=None, binary_reports=None, rootdir=None)

Render a run’s reports into the artifact store; return `{format: key}`.

The single place that knows how a run’s reports are named and where they
go, so the CLI, the library and any future surface cannot drift apart on it.

`key` defaults to `<repo-slug>/<timestamp>` — per run, so re-analysing a
repository never overwrites the answer you are comparing against. Nothing is
written into the analysed repository, ever: see [`mergeset.storage`](mergeset.storage.html.md#module-mergeset.storage).

```pycon
>>> from mergeset.analysis import Analysis
>>> a = Analysis(repo='/x/y/proj', base='main', base_sha='0'*40, changes=[])
>>> text, binary = {}, {}
>>> written = write_reports(a, key='run-1', reports=text, binary_reports=binary)
>>> sorted(written)
['html', 'markdown']
>>> sorted(text)
['run-1/REPORT.md', 'run-1/report.html']
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
