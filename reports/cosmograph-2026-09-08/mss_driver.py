"""Ad-hoc MSS driver for the cosmograph PR set (TEST workstream, pre-tool).

A *change* here is one PR.  Because several PRs are stacked, a set of PRs is only
meaningful when it is **prefix-closed** in its stack (you cannot land #616 without
#604 and #587).  We therefore:

  1. close a requested set upwards through `parent_pr`
  2. reduce it to the *tips* (PRs no other member descends from) -- merging a tip
     brings its ancestors along for free
  3. merge those tips onto origin/main in the object database (no worktree)
  4. if that is textually clean, materialise the merge commit in one scratch
     worktree and run the local equivalent of CI's Lint + Unit Tests jobs.

Every evaluation is appended to `evaluations.jsonl`, which is the single source
of truth; the known-good / known-bad closure is re-derived from it.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

WORK = Path(__file__).resolve().parent
REPO = WORK.parent / "repo"
LOG = WORK / "evaluations.jsonl"
sys.path.insert(0, str(WORK))
from seqmerge import merge_sequence, git  # noqa: E402

PRE = json.loads((WORK / "preoracle.json").read_text())["prs"]
HEAD = {int(k): v["head"] for k, v in PRE.items()}
PARENT = {int(k): v["parent_pr"] for k, v in PRE.items()}
ALL = sorted(HEAD)


def closure(prs):
    """Prefix-close a set of PRs through the stack parent relation."""
    out = set(prs)
    changed = True
    while changed:
        changed = False
        for n in list(out):
            p = PARENT.get(n)
            if p is not None and p not in out:
                out.add(p)
                changed = True
    return sorted(out)


def tips(prs):
    """Members that are not the parent of another member (merge these branches)."""
    s = set(prs)
    parents = {PARENT[n] for n in s if PARENT.get(n) in s}
    return sorted(s - parents)


def label(prs):
    return "s" + "-".join(str(n) for n in prs)


def evaluate(prs, why=""):
    prs = closure(prs)
    lab = label(prs)
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        rec = json.loads(line)
        if rec["label"] == lab:
            print(f"[cached] {lab}: {rec['verdict']}")
            return rec
    t = tips(prs)
    m = merge_sequence([HEAD[n] for n in t])
    rec = {
        "label": lab,
        "prs": prs,
        "tips": t,
        "why": why,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if not m.clean:
        rec.update(
            verdict="fail",
            stage="merge",
            failed_at=m.failed_at,
            conflicted_files=m.conflicted_files,
            secs=0,
        )
        print(f"[merge-conflict] {lab} at {m.failed_at}: {m.conflicted_files}")
    else:
        git("update-ref", f"refs/mergeset/{lab}", m.commit)
        r = subprocess.run(
            [str(WORK / "evaluate.sh"), m.commit, lab], capture_output=True, text=True
        )
        out = (
            r.stdout.strip().splitlines()[-1]
            if r.stdout.strip()
            else "RESULT parse-fail"
        )
        kv = dict(p.split("=", 1) for p in out.split()[1:] if "=" in p)
        ok = kv.get("build") == "0" and kv.get("test") == "0" and kv.get("lint") == "0"
        rec.update(
            verdict="pass" if ok else "fail",
            stage="validate",
            commit=m.commit,
            build=kv.get("build"),
            test=kv.get("test"),
            lint=kv.get("lint"),
            secs=int(kv.get("secs", 0)),
        )
        if not ok:
            rec["failing"] = _failing_tests(lab)
        print(
            f"[{rec['verdict']}] {lab} build={kv.get('build')} test={kv.get('test')} "
            f"lint={kv.get('lint')} {kv.get('secs')}s"
        )
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def _failing_tests(lab):
    p = WORK / "logs" / f"{lab}.log"
    if not p.exists():
        return []
    keep = [
        ln.strip()
        for ln in p.read_text().splitlines()
        if ln.strip().startswith(("FAIL", "✗", "×", "❯ ")) or " error " in ln.lower()
    ]
    return keep[:60]


if __name__ == "__main__":
    if sys.argv[1:] == ["all"]:
        evaluate(ALL, why="full union")
    else:
        evaluate([int(x) for x in sys.argv[1:]], why="manual")
