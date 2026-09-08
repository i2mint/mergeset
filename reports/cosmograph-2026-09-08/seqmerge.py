"""Sequential in-memory merge oracle for the cosmograph mergeset analysis.

`git merge-tree --write-tree A B` merges using merge-base(A, B), which is the
WRONG base when the two branches have different merge-bases with `main` (a stale
branch then reports main's own commits as conflicts).  What we actually want is
"merge each change onto current main, one after another".  We get that with no
worktree at all by chaining: merge-tree the accumulated commit with the next
branch, `commit-tree` the resulting tree, and feed it back in.

Exposes:
    merge_sequence(refs) -> MergeResult
    pairwise(refs)       -> dict of pair -> MergeResult
"""

import json
import subprocess
from dataclasses import dataclass, field, asdict
from itertools import combinations
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "repo"
WORK = Path(__file__).resolve().parent
BASE = "origin/main"


def git(*args, check=True, **kw):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} -> {r.returncode}\n{r.stderr}")
    return r


@dataclass
class MergeResult:
    refs: list
    clean: bool
    commit: str = ""
    failed_at: str = ""
    conflicted_files: list = field(default_factory=list)


def _commit_tree(tree, parents, msg):
    args = ["commit-tree", tree]
    for p in parents:
        args += ["-p", p]
    env_free = git(*args, "-m", msg,
                   env={"GIT_AUTHOR_NAME": "mergeset", "GIT_AUTHOR_EMAIL": "m@x",
                        "GIT_COMMITTER_NAME": "mergeset", "GIT_COMMITTER_EMAIL": "m@x",
                        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                        "HOME": str(Path.home())})
    return env_free.stdout.strip()


def merge_sequence(refs, base=BASE):
    """Merge `refs` onto `base` one at a time, entirely in the object database."""
    acc = git("rev-parse", base).stdout.strip()
    for ref in refs:
        head = git("rev-parse", f"origin/{ref}").stdout.strip()
        r = git("merge-tree", "--write-tree", "--name-only", acc, head, check=False)
        lines = r.stdout.splitlines()
        if r.returncode != 0:
            files = []
            for ln in lines[1:]:
                if not ln.strip():
                    break
                files.append(ln.strip())
            return MergeResult(list(refs), False, failed_at=ref, conflicted_files=files)
        tree = lines[0].strip()
        acc = _commit_tree(tree, [acc, head], f"merge {ref}")
    return MergeResult(list(refs), True, commit=acc)


def pairwise(refs):
    out = {}
    for a, b in combinations(refs, 2):
        out[f"{a}|{b}"] = asdict(merge_sequence([a, b]))
    return out


if __name__ == "__main__":
    import sys
    pr_head = json.loads((WORK / "preoracle.json").read_text())["prs"]
    heads = {int(k): v["head"] for k, v in pr_head.items()}
    if len(sys.argv) > 1:
        nums = [int(x) for x in sys.argv[1:]]
        res = merge_sequence([heads[n] for n in nums])
        print(json.dumps(asdict(res), indent=2))
    else:
        # singletons onto current main
        print("== singleton merges onto origin/main ==")
        sing = {}
        for n, h in sorted(heads.items()):
            r = merge_sequence([h])
            sing[n] = asdict(r)
            print(f"  #{n} {h:<32} {'clean' if r.clean else 'CONFLICT ' + str(r.conflicted_files)}")
        print("\n== pairwise sequential merges onto origin/main ==")
        pw = {}
        for a, b in combinations(sorted(heads), 2):
            r = merge_sequence([heads[a], heads[b]])
            pw[f"{a}+{b}"] = asdict(r)
            if not r.clean:
                print(f"  #{a}+#{b}: CONFLICT at {r.failed_at}: {r.conflicted_files}")
        print("  (pairs not listed merged clean)")
        (WORK / "seqmerge.json").write_text(json.dumps({"singletons": sing, "pairs": pw}, indent=2))
