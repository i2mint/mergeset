"""Create one local integration branch per maximal good set.

Local only: no push, no existing branch touched.  Each branch points at the
merge commit already built (and validated) by `mergeset.py`, so the branch is
exactly the tree that was tested.
"""

import json
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK))
from seqmerge import git  # noqa: E402
from mss_driver import label, closure  # noqa: E402

DATE = "2026-09-08"


def main():
    sets = json.loads((WORK / "conflicts.json").read_text())["maximal_good_sets"]
    evals = {
        json.loads(l)["label"]: json.loads(l)
        for l in (WORK / "evaluations.jsonl").read_text().splitlines()
        if l.strip()
    }
    out = []
    for m in sets:
        lab = label(closure(m["prs"]))
        rec = evals.get(lab)
        if not rec or not rec.get("commit"):
            out.append((m["name"], None, "no validated merge commit"))
            continue
        name = f"integration/{DATE}-{m['name'].lower()}"
        git("branch", "-f", name, rec["commit"])
        out.append((m["name"], name, rec["commit"][:12]))
    for n, b, c in out:
        print(f"{n:<6} {b or '-':<34} {c}")


if __name__ == "__main__":
    main()
