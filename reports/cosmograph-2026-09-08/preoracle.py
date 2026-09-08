"""Ad-hoc pre-oracles for the cosmograph mergeset analysis (TEST workstream).

Cheap, git-only signals computed before any test run:
  * stack ancestry (which PR head contains which PR base)
  * pairwise textual mergeability via `git merge-tree --write-tree`
  * changed-file overlap graph and its connected components
"""

import json
import subprocess
from itertools import combinations
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "repo"
WORK = Path(__file__).resolve().parent
BASE = "origin/main"


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} -> {r.returncode}\n{r.stderr}")
    return r


def _prs():
    prs = json.loads((WORK / "prs.json").read_text())
    recent = {575, 576, 577, 579, 587, 602, 604, 616, 630, 631, 632, 633, 634, 636, 637}
    return {p["number"]: p for p in prs if p["number"] in recent}


def changed_files(ref):
    out = git("diff", "--name-only", f"{BASE}...origin/{ref}").stdout
    return set(filter(None, out.splitlines()))


def merge_tree(a, b):
    """Return (clean, conflicted_files) for merging origin/a and origin/b."""
    r = git(
        "merge-tree",
        "--write-tree",
        "--name-only",
        f"origin/{a}",
        f"origin/{b}",
        check=False,
    )
    if r.returncode == 0:
        return True, []
    lines = r.stdout.splitlines()
    # first line is the tree oid, then conflicted paths until a blank line
    files = []
    for ln in lines[1:]:
        if not ln.strip():
            break
        files.append(ln.strip())
    return False, files


def main():
    prs = _prs()
    heads = {n: p["headRefName"] for n, p in prs.items()}
    bases = {n: p["baseRefName"] for n, p in prs.items()}
    head_to_pr = {v: k for k, v in heads.items()}

    report = {"base_sha": git("rev-parse", BASE).stdout.strip(), "prs": {}}

    for n, p in sorted(prs.items()):
        files = changed_files(heads[n])
        parent = head_to_pr.get(bases[n])
        anc = None
        if parent is not None:
            anc = (
                git(
                    "merge-base",
                    "--is-ancestor",
                    f"origin/{heads[parent]}",
                    f"origin/{heads[n]}",
                    check=False,
                ).returncode
                == 0
            )
        report["prs"][n] = {
            "head": heads[n],
            "base": bases[n],
            "parent_pr": parent,
            "parent_is_ancestor": anc,
            "commits_vs_main": int(
                git("rev-list", "--count", f"{BASE}..origin/{heads[n]}").stdout
            ),
            "files": sorted(files),
            "n_files": len(files),
            "insertions_deletions": git(
                "diff", "--shortstat", f"{BASE}...origin/{heads[n]}"
            ).stdout.strip(),
        }

    # pairwise textual merge + file overlap
    pairs = {}
    for a, b in combinations(sorted(prs), 2):
        clean, conf = merge_tree(heads[a], heads[b])
        overlap = sorted(
            set(report["prs"][a]["files"]) & set(report["prs"][b]["files"])
        )
        pairs[f"{a}+{b}"] = {
            "textually_clean": clean,
            "conflicted_files": conf,
            "file_overlap": overlap,
            "n_overlap": len(overlap),
        }
    report["pairs"] = pairs
    (WORK / "preoracle.json").write_text(json.dumps(report, indent=2))

    print(f"base {report['base_sha'][:8]}  {len(prs)} PRs")
    print("\n== stack structure ==")
    for n, d in sorted(report["prs"].items()):
        pp = f"child of #{d['parent_pr']}" if d["parent_pr"] else "on main"
        anc = (
            ""
            if d["parent_is_ancestor"] in (None, True)
            else "  ** BASE NOT ANCESTOR (needs rebase) **"
        )
        print(
            f"  #{n} {d['head']:<32} {pp:<14} {d['n_files']:>3} files  {d['insertions_deletions']}{anc}"
        )

    print("\n== pairwise textual conflicts (git merge-tree) ==")
    any_c = False
    for k, v in pairs.items():
        if not v["textually_clean"]:
            any_c = True
            print(f"  {k}: {v['conflicted_files']}")
    if not any_c:
        print("  none")

    print("\n== file overlap (pairs sharing >=1 changed file) ==")
    for k, v in sorted(pairs.items(), key=lambda kv: -kv[1]["n_overlap"]):
        if v["n_overlap"]:
            print(f"  {k}: {v['n_overlap']} files  e.g. {v['file_overlap'][:3]}")


if __name__ == "__main__":
    main()
