"""Rendering an :class:`~mergeset.analysis.Analysis` for humans.

Two renderers: a Markdown report meant to be read in a terminal or a PR comment,
and a single self-contained HTML file (no build step, no CDN) meant to be opened
and poked at. Both are pure functions of the analysis, which is itself derived
from the evaluation log — so a report can always be regenerated without
re-running anything expensive.
"""

from __future__ import annotations

import html
import json
from typing import Iterable, Iterator, List, Optional

from mergeset.analysis import Analysis
from mergeset.base import ChangeSet, set_key


def _fmt_set(subset: Iterable[str]) -> str:
    return ", ".join(f"`{c}`" for c in sorted(subset)) or "_(none)_"


def markdown_report(analysis: Analysis, *, title: str = "mergeset report") -> str:
    """Render the analysis as Markdown.

    Sections, in the order a reader actually wants them: what to merge, what
    stops the rest, and only then the evidence.
    """
    return "\n".join(_markdown_lines(analysis, title))


def _markdown_lines(analysis: Analysis, title: str) -> Iterator[str]:
    by_id = analysis.by_id
    yield f"# {title}"
    yield ""
    yield (
        f"Base `{analysis.base}` (`{analysis.base_sha[:8]}`) · "
        f"{len(analysis.changes)} candidate changes · "
        f"{analysis.evaluations} expensive evaluations spent · "
        f"{'complete' if analysis.exhausted else 'partial (budget reached)'}"
    )
    yield ""

    yield "## Recommended merge plans"
    yield ""
    plans = analysis.merge_plan()
    if not plans:
        yield "_No good set was found. Every candidate conflicts._"
    for plan in plans:
        yield (
            f"### Plan {plan['rank']} — merge {plan['size']} of "
            f"{len(analysis.changes)}"
        )
        yield ""
        yield "Merge in this order:"
        yield ""
        for i, cid in enumerate(plan["merge"], start=1):
            change = by_id.get(cid)
            meta = change.meta if change else {}
            label = meta.get("title") or (change.head if change else "")
            url = meta.get("url")
            name = f"[`{cid}`]({url})" if url else f"`{cid}`"
            yield f"{i}. {name} — {label}"
        yield ""
        if len(plan["merge"]) < len(plan["changes"]):
            brought = sorted(set(plan["changes"]) - set(plan["merge"]))
            yield (
                f"That merges {len(plan['merge'])} refs and lands "
                f"{len(plan['changes'])} changes: {_fmt_set(brought)} come along "
                "as ancestors of the branches above."
            )
            yield ""
        yield f"Dropped: {_fmt_set(plan['dropped'])} (weight {plan['dropped_weight']})"
        yield ""

    yield "## What stops the rest"
    yield ""
    if analysis.singleton_conflicts:
        yield "**Will not merge onto the base at all** (before any test ran):"
        yield ""
        for cid, files in sorted(analysis.singleton_conflicts.items()):
            shown = ", ".join(f"`{f}`" for f in files[:5]) or "_(unattributed)_"
            yield f"- `{cid}` — {shown}"
        yield ""
    if analysis.textual_conflicts:
        yield "**Textual conflicts** (found by `git merge-tree`, before any test ran):"
        yield ""
        yield "| a | b | files |"
        yield "| --- | --- | --- |"
        for a, b, files in analysis.textual_conflicts:
            shown = ", ".join(f"`{f}`" for f in files[:5]) or "_(unattributed)_"
            more = f" (+{len(files) - 5} more)" if len(files) > 5 else ""
            yield f"| `{a}` | `{b}` | {shown}{more} |"
        yield ""
    semantic = [
        c for c in analysis.conflicts
        if not any(
            frozenset({a, b}) == c for a, b, _ in analysis.textual_conflicts
        )
    ]
    if semantic:
        yield "**Conflicts found by validation** (merged cleanly, still failed):"
        yield ""
        for conflict in sorted(semantic, key=lambda s: (len(s), set_key(s))):
            evidence = _failure_evidence(analysis, conflict)
            yield f"- {_fmt_set(conflict)}{evidence}"
        yield ""
    if not analysis.textual_conflicts and not semantic and not analysis.singleton_conflicts:
        yield "_Nothing. Every candidate merges and validates together._"
        yield ""

    yield "## Candidates"
    yield ""
    yield "| change | source | head | weight | files | notes |"
    yield "| --- | --- | --- | --- | --- | --- |"
    for change in sorted(analysis.changes, key=lambda c: c.id):
        files = analysis.files_by_change.get(change.id, [])
        notes = []
        if change.id in analysis.stacks:
            notes.append(f"stacked on `{analysis.stacks[change.id]}`")
        if change.meta.get("draft"):
            notes.append("draft")
        if change.meta.get("ci"):
            notes.append(f"CI {change.meta['ci']}")
        yield (
            f"| `{change.id}` | {change.source} | `{change.head}` | "
            f"{analysis.weights.get(change.id, 1.0):.2f} | {len(files)} | "
            f"{'; '.join(notes)} |"
        )
    yield ""

    if len(analysis.components) > 1:
        yield "## Independent components"
        yield ""
        yield (
            "These groups touch no common file, so they were solved separately "
            "and their answers combine freely."
        )
        yield ""
        for i, component in enumerate(analysis.components, start=1):
            yield f"{i}. {_fmt_set(component)}"
        yield ""

    if analysis.notes:
        yield "## Notes"
        yield ""
        for note in analysis.notes:
            yield f"- {note}"
        yield ""

    yield "## Evaluation log"
    yield ""
    yield f"{len(analysis.log or [])} rows. Every row is re-usable: a re-run costs nothing for sets already decided."
    yield ""
    yield "| set | verdict | stage | seconds | detail |"
    yield "| --- | --- | --- | --- | --- |"
    for record in analysis.log or []:
        detail = ""
        if record.merge and not record.merge.ok:
            detail = "conflict: " + ", ".join(f"`{f}`" for f in record.merge.conflicting_files[:3])
        elif record.validation and not record.validation.ok:
            detail = ", ".join(f"`{t}`" for t in record.validation.failing_tests[:3])
        if record.merge and record.merge.assisted:
            detail += " **(assisted resolution — review the diff)**"
        yield (
            f"| {_fmt_set(record.subset)} | {record.verdict.value} | "
            f"{record.stage.value if record.stage else ''} | "
            f"{record.duration:.1f} | {detail} |"
        )


def _failure_evidence(analysis: Analysis, conflict: ChangeSet) -> str:
    """Which tests, if we know — the difference between a report and an oracle."""
    for record in analysis.log or []:
        if record.subset == conflict and record.validation:
            tests = record.validation.failing_tests[:3]
            if tests:
                return " — failing: " + ", ".join(f"`{t}`" for t in tests)
    return ""


def html_report(analysis: Analysis, *, title: str = "mergeset") -> str:
    """Render the analysis as one self-contained HTML file.

    No build step, no CDN, no network: a single file that can be opened from
    disk or attached to an issue. It draws the conflict graph (nodes = changes,
    edges = conflicts, textual vs validation distinguished), the maximal sets,
    and the evaluation timeline.
    """
    data = _analysis_jdict(analysis)
    return _HTML_TEMPLATE.replace("__TITLE__", html.escape(title)).replace(
        "__DATA__", json.dumps(data)
    )


def _analysis_jdict(analysis: Analysis) -> dict:
    """The whole analysis as JSON, which is what the HTML page renders."""
    textual_pairs = {frozenset({a, b}) for a, b, _ in analysis.textual_conflicts}
    return {
        "base": analysis.base,
        "base_sha": analysis.base_sha,
        "exhausted": analysis.exhausted,
        "evaluations": analysis.evaluations,
        "changes": [
            {
                **c.to_jdict(),
                "weight": analysis.weights.get(c.id, 1.0),
                "files": analysis.files_by_change.get(c.id, []),
                "stacked_on": analysis.stacks.get(c.id),
                "component": next(
                    (i for i, comp in enumerate(analysis.components) if c.id in comp), 0
                ),
            }
            for c in analysis.changes
        ],
        "edges": [
            {"a": a, "b": b, "kind": "textual", "files": files}
            for a, b, files in analysis.textual_conflicts
        ]
        + [
            {"a": sorted(c)[0], "b": sorted(c)[1], "kind": "validation", "files": []}
            for c in analysis.conflicts
            if len(c) == 2 and c not in textual_pairs
        ],
        "big_conflicts": [
            list(set_key(c)) for c in analysis.conflicts if len(c) > 2
        ],
        "plans": analysis.merge_plan(),
        "components": [list(set_key(c)) for c in analysis.components],
        "singleton_conflicts": {
            k: v for k, v in analysis.singleton_conflicts.items()
        },
        "stacks": dict(analysis.stacks),
        "notes": analysis.notes,
        "log": [e.to_jdict() for e in (analysis.log or [])],
    }


_HTML_TEMPLATE = r"""<!doctype html>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root { color-scheme: light dark;
    --bg:#fbfbfa; --fg:#1a1a19; --muted:#6b6b66; --line:#dedcd6;
    --card:#ffffff; --good:#2f7d4f; --bad:#b3452e; --warn:#8a6a1f; --accent:#3b5b9e; }
  @media (prefers-color-scheme: dark) { :root {
    --bg:#161614; --fg:#eceae4; --muted:#9a978e; --line:#33312c;
    --card:#1f1e1b; --good:#6fbf8b; --bad:#e08a72; --warn:#d8b45c; --accent:#8fa9dd; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 32px 20px 80px; }
  h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
  h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .08em;
       color: var(--muted); margin: 36px 0 12px; font-weight: 600; }
  .sub { color: var(--muted); margin-bottom: 8px; }
  .card { background: var(--card); border: 1px solid var(--line);
          border-radius: 10px; padding: 16px 18px; margin-bottom: 12px; }
  code, .mono { font-family: ui-monospace,SFMono-Regular,Menlo,monospace; font-size: 13px; }
  .pill { display:inline-block; padding:1px 8px; border-radius:999px;
          border:1px solid var(--line); font-size:12px; margin-right:6px; }
  .good { color: var(--good); } .bad { color: var(--bad); } .warn { color: var(--warn); }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line);
           vertical-align: top; }
  th { color: var(--muted); font-weight: 600; }
  .scroll { overflow-x: auto; }
  svg { width: 100%; height: auto; display: block; }
  .node { cursor: default; }
  .edge-textual { stroke: var(--bad); stroke-width: 2; }
  .edge-validation { stroke: var(--warn); stroke-width: 2; stroke-dasharray: 5 4; }
  .legend { color: var(--muted); font-size: 12px; margin-top: 8px; }
  ol { margin: 6px 0 0 20px; padding: 0; }
</style>
<div class="wrap">
  <h1>__TITLE__</h1>
  <div class="sub" id="summary"></div>
  <h2>Conflict graph</h2>
  <div class="card"><div id="graph"></div>
    <div class="legend">Solid red = textual conflict (<code>git merge-tree</code>, no test run).
      Dashed amber = found by validation. Node size = weight. Colour = component.</div>
  </div>
  <h2>Merge plans</h2><div id="plans"></div>
  <h2>Candidates</h2><div class="card scroll"><table id="changes"></table></div>
  <h2>Notes</h2><div class="card" id="notes"></div>
  <h2>Evaluation log</h2><div class="card scroll"><table id="log"></table></div>
</div>
<script>
const DATA = __DATA__;
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const COLORS = ['#3b5b9e','#2f7d4f','#8a6a1f','#7a3f8f','#b3452e','#2f7d7d'];

document.getElementById('summary').innerHTML =
  `base <code>${esc(DATA.base)}</code> (<code>${esc(DATA.base_sha.slice(0,8))}</code>) · ` +
  `${DATA.changes.length} changes · ${DATA.evaluations} evaluations · ` +
  (DATA.exhausted ? '<span class="good">complete</span>'
                  : '<span class="warn">partial (budget reached)</span>');

// --- conflict graph: changes on a circle, conflicts as chords -------------
(function drawGraph(){
  const n = DATA.changes.length, W = 900, H = Math.max(320, 60 + n * 26);
  const cx = W/2, cy = H/2, R = Math.min(W, H)/2 - 90;
  const pos = {};
  DATA.changes.forEach((c, i) => {
    const a = (i / n) * 2 * Math.PI - Math.PI/2;
    pos[c.id] = { x: cx + R*Math.cos(a), y: cy + R*Math.sin(a), a };
  });
  const maxW = Math.max(1, ...DATA.changes.map(c => c.weight || 1));
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="conflict graph">`;
  DATA.edges.forEach(e => {
    const p = pos[e.a], q = pos[e.b];
    if (!p || !q) return;
    svg += `<path class="edge-${e.kind}" fill="none" d="M${p.x} ${p.y} Q ${cx} ${cy} ${q.x} ${q.y}">` +
           `<title>${esc(e.a)} × ${esc(e.b)}${e.files.length ? ': ' + esc(e.files.slice(0,6).join(', ')) : ''}</title></path>`;
  });
  DATA.changes.forEach(c => {
    const p = pos[c.id], r = 6 + 8 * ((c.weight || 1) / maxW);
    const color = COLORS[(c.component || 0) % COLORS.length];
    const right = Math.cos(p.a) > -0.01;
    svg += `<circle class="node" cx="${p.x}" cy="${p.y}" r="${r}" fill="${color}" opacity="0.85">` +
           `<title>${esc(c.id)} — ${esc((c.meta && c.meta.title) || c.head)}\n${c.files.length} files</title></circle>`;
    svg += `<text x="${p.x + (right ? r+6 : -r-6)}" y="${p.y+4}" font-size="12" ` +
           `text-anchor="${right ? 'start' : 'end'}" fill="currentColor">${esc(c.id)}</text>`;
  });
  document.getElementById('graph').innerHTML = svg + '</svg>';
})();

document.getElementById('plans').innerHTML = DATA.plans.length ? DATA.plans.map(p =>
  `<div class="card"><b>Plan ${p.rank}</b> — merge ${p.size} of ${DATA.changes.length}
   <span class="pill">dropped weight ${p.dropped_weight}</span>
   <ol>${p.changes.map(id => {
     const c = DATA.changes.find(x => x.id === id) || {};
     const t = (c.meta && c.meta.title) || c.head || '';
     const u = c.meta && c.meta.url;
     return `<li>${u ? `<a href="${esc(u)}">` : ''}<code>${esc(id)}</code>${u ? '</a>' : ''} — ${esc(t)}</li>`;
   }).join('')}</ol>
   <div class="sub">drops: ${p.dropped.length ? p.dropped.map(d => `<code>${esc(d)}</code>`).join(' ') : '<i>nothing</i>'}</div>
   </div>`).join('') : '<div class="card">No good set found.</div>';

document.getElementById('changes').innerHTML =
  '<tr><th>change</th><th>source</th><th>head</th><th>weight</th><th>files</th><th>notes</th></tr>' +
  DATA.changes.map(c => {
    const notes = [];
    if (c.stacked_on) notes.push(`stacked on <code>${esc(c.stacked_on)}</code>`);
    if (c.meta && c.meta.draft) notes.push('draft');
    if (c.meta && c.meta.ci) notes.push('CI ' + esc(c.meta.ci));
    return `<tr><td><code>${esc(c.id)}</code></td><td>${esc(c.source)}</td>` +
      `<td><code>${esc(c.head)}</code></td><td>${(c.weight||1).toFixed(2)}</td>` +
      `<td>${c.files.length}</td><td>${notes.join('; ')}</td></tr>`;
  }).join('');

document.getElementById('notes').innerHTML = DATA.notes.length
  ? '<ul>' + DATA.notes.map(n => `<li>${esc(n)}</li>`).join('') + '</ul>'
  : '<i>none</i>';

document.getElementById('log').innerHTML =
  '<tr><th>set</th><th>verdict</th><th>stage</th><th>s</th><th>detail</th></tr>' +
  DATA.log.map(e => {
    let detail = '';
    if (e.merge && !e.merge.ok) detail = 'conflict: ' + esc(e.merge.conflicting_files.slice(0,3).join(', '));
    else if (e.validation && !e.validation.ok) detail = esc(e.validation.failing_tests.slice(0,3).join(', '));
    if (e.merge && e.merge.assisted) detail += ' <b class="warn">(assisted)</b>';
    const cls = e.verdict === 'pass' ? 'good' : e.verdict === 'fail' ? 'bad' : 'warn';
    return `<tr><td><code>${esc(e.subset.join(', '))}</code></td>` +
      `<td class="${cls}">${esc(e.verdict)}</td><td>${esc(e.stage || '')}</td>` +
      `<td>${(e.duration||0).toFixed(1)}</td><td>${detail}</td></tr>`;
  }).join('');
</script>
"""
