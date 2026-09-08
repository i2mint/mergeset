"""Render the cosmograph merge-set analysis as a single self-contained HTML page.

Everything is derived from `preoracle.json` (git-only pre-oracles) and
`evaluations.jsonl` (the evaluation log, which is the source of truth).
No build step, no external assets, no network.
"""

import html
import json
from pathlib import Path

WORK = Path(__file__).resolve().parent

TITLE = "cosmograph merge sets — 2026-09-08"

GROUPS = {
    "graph-ops": [575, 576, 577, 579],
    "stories": [587, 602, 604, 616],
    "SSOT": [631, 633, 634, 636, 637],
    "solo": [630, 632],
}


def load():
    pre = json.loads((WORK / "preoracle.json").read_text())
    evals = [json.loads(l) for l in (WORK / "evaluations.jsonl").read_text().splitlines() if l.strip()]
    conflicts = json.loads((WORK / "conflicts.json").read_text())
    return pre, evals, conflicts


def esc(s):
    return html.escape(str(s))


def render(pre, evals, conflicts, out):
    prs = pre["prs"]
    order = [n for g in GROUPS.values() for n in g]
    # node positions: one column per group
    cols = list(GROUPS)
    W, H = 980, 420
    colw = W / len(cols)
    pos = {}
    for ci, g in enumerate(cols):
        members = GROUPS[g]
        for ri, n in enumerate(members):
            pos[n] = (colw * ci + colw / 2, 70 + ri * 78)

    def node_class(n):
        for c in conflicts["minimal_conflicts"]:
            if c["prs"] == [n]:
                return "bad"
        return "ok"

    svg = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="conflict graph">']
    # stack edges
    for n, d in prs.items():
        n = int(n)
        p = d["parent_pr"]
        if p:
            x1, y1 = pos[p]; x2, y2 = pos[n]
            svg.append(f'<line class="stack" x1="{x1}" y1="{y1+16}" x2="{x2}" y2="{y2-16}"/>')
    # conflict edges
    for c in conflicts["minimal_conflicts"]:
        if len(c["prs"]) == 2:
            a, b = c["prs"]
            x1, y1 = pos[a]; x2, y2 = pos[b]
            cls = "textual" if c["kind"] == "textual" else "semantic"
            svg.append(f'<path class="conf {cls}" d="M{x1},{y1} Q{(x1+x2)/2},{min(y1,y2)-60} {x2},{y2}"/>')
    for n in order:
        x, y = pos[n]
        svg.append(
            f'<g class="node {node_class(n)}"><circle cx="{x}" cy="{y}" r="19"/>'
            f'<text x="{x}" y="{y+4}">{n}</text></g>'
        )
    for ci, g in enumerate(cols):
        svg.append(f'<text class="grp" x="{colw*ci+colw/2}" y="30">{esc(g)}</text>')
    svg.append("</svg>")

    rows = []
    for e in evals:
        verdict = e["verdict"]
        detail = (
            f"merge conflict at <code>{esc(e.get('failed_at',''))}</code>: "
            + ", ".join(f"<code>{esc(f)}</code>" for f in e.get("conflicted_files", []))
            if e.get("stage") == "merge"
            else f"build={esc(e.get('build'))} test={esc(e.get('test'))} lint={esc(e.get('lint'))}"
        )
        rows.append(
            f"<tr class='{verdict}'><td>{' '.join('#'+str(p) for p in e['prs'])}</td>"
            f"<td class='v'>{verdict}</td><td>{esc(e.get('secs',0))}s</td>"
            f"<td>{detail}</td><td class='why'>{esc(e.get('why',''))}</td></tr>"
        )

    mss_rows = []
    for m in conflicts["maximal_good_sets"]:
        mss_rows.append(
            f"<tr><td class='mss'>{m['name']}</td><td>{len(m['prs'])}</td>"
            f"<td>{' '.join('#'+str(p) for p in m['prs'])}</td>"
            f"<td>{' '.join('#'+str(p) for p in m['dropped'])}</td>"
            f"<td>{esc(m['verdict'])}</td></tr>"
        )

    conf_rows = []
    for c in conflicts["minimal_conflicts"]:
        conf_rows.append(
            f"<tr><td>{' '.join('#'+str(p) for p in c['prs'])}</td>"
            f"<td class='{c['kind']}'>{c['kind']}</td><td>{c['evidence']}</td></tr>"
        )

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(TITLE)}</title><style>
:root {{ --bg:#fdfdfc; --fg:#1c1b19; --mut:#6b6864; --line:#dcd8d2;
  --ok:#2f7d55; --bad:#b3392e; --sem:#9a5b12; --card:#ffffff; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme=light]) {{
  --bg:#16171a; --fg:#e8e6e3; --mut:#9b9691; --line:#2f3136; --card:#1d1f23; }} }}
:root[data-theme=dark] {{ --bg:#16171a; --fg:#e8e6e3; --mut:#9b9691; --line:#2f3136; --card:#1d1f23; }}
* {{ box-sizing:border-box }}
body {{ background:var(--bg); color:var(--fg); margin:0;
  font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1040px; margin:0 auto; padding:36px 22px 80px }}
h1 {{ font-size:1.6rem; margin:0 0 4px; letter-spacing:-.01em }}
h2 {{ font-size:1.05rem; margin:38px 0 10px; letter-spacing:.02em; text-transform:uppercase;
  color:var(--mut); font-weight:600 }}
p.sub {{ color:var(--mut); margin:0 0 8px }}
code {{ font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
  background:color-mix(in srgb,var(--fg) 7%,transparent); padding:1px 4px; border-radius:3px }}
figure {{ margin:0; background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:8px; overflow-x:auto }}
svg {{ width:100%; min-width:700px; height:auto; display:block }}
.node circle {{ fill:var(--card); stroke:var(--ok); stroke-width:2 }}
.node.bad circle {{ stroke:var(--bad); stroke-dasharray:3 3 }}
.node text {{ text-anchor:middle; font:600 12px ui-monospace,monospace; fill:var(--fg) }}
.grp {{ text-anchor:middle; font:600 12px ui-sans-serif,sans-serif; fill:var(--mut);
  text-transform:uppercase; letter-spacing:.08em }}
line.stack {{ stroke:var(--line); stroke-width:2 }}
path.conf {{ fill:none; stroke-width:2.5 }}
path.textual {{ stroke:var(--bad) }}
path.semantic {{ stroke:var(--sem); stroke-dasharray:6 4 }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px }}
th,td {{ text-align:left; padding:7px 9px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ color:var(--mut); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.05em }}
tr.pass td.v {{ color:var(--ok); font-weight:600 }}
tr.fail td.v {{ color:var(--bad); font-weight:600 }}
td.textual {{ color:var(--bad); font-weight:600 }}
td.semantic {{ color:var(--sem); font-weight:600 }}
td.why, .mut {{ color:var(--mut) }}
td.mss {{ font-weight:600; white-space:nowrap }}
.legend {{ display:flex; gap:20px; flex-wrap:wrap; color:var(--mut); font-size:12.5px; margin-top:10px }}
.sw {{ display:inline-block; width:22px; height:0; border-top:2.5px solid; vertical-align:middle; margin-right:6px }}
.wrap {{ overflow-x:auto }}
</style></head><body><main>
<h1>{esc(TITLE)}</h1>
<p class="sub">15 open PRs by <code>thorwhalen</code> on <code>cosmograph-org/cosmograph</code>, merged onto
<code>origin/main</code> @ <code>{esc(pre['base_sha'][:8])}</code>. Grey lines are stack relationships
(a PR based on another PR); coloured arcs are conflicts.</p>

<h2>Changes and conflicts</h2>
<figure>{''.join(svg)}</figure>
<div class="legend">
  <span><span class="sw" style="border-color:var(--line)"></span>stack (base → head)</span>
  <span><span class="sw" style="border-color:var(--bad)"></span>textual conflict</span>
  <span><span class="sw" style="border-color:var(--sem);border-top-style:dashed"></span>semantic conflict (tests)</span>
  <span><span class="sw" style="border-color:var(--bad);border-top-style:dashed"></span>dashed circle = conflicts with base alone</span>
</div>

<h2>Minimal conflicts</h2>
<div class="wrap"><table><thead><tr><th>changes</th><th>kind</th><th>evidence</th></tr></thead>
<tbody>{''.join(conf_rows)}</tbody></table></div>

<h2>Maximal good sets</h2>
<div class="wrap"><table><thead><tr><th>set</th><th>n</th><th>PRs</th><th>dropped</th><th>verified</th></tr></thead>
<tbody>{''.join(mss_rows)}</tbody></table></div>

<h2>Evaluation log</h2>
<p class="sub">{len(evals)} evaluations. Validation = <code>pnpm run build:cosmos</code> +
<code>pnpm run test</code> + <code>pnpm run lint:ci</code>, the local equivalent of CI's Lint and Unit Tests jobs.</p>
<div class="wrap"><table><thead><tr><th>set</th><th>verdict</th><th>time</th><th>detail</th><th>why evaluated</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
</main></body></html>"""
    Path(out).write_text(doc)
    print(f"wrote {out}")


if __name__ == "__main__":
    import sys
    pre, evals, conflicts = load()
    render(pre, evals, conflicts, sys.argv[1])
