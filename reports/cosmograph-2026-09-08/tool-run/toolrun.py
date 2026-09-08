"""Re-run the cosmograph analysis through the `mergeset` package (TEST step 3).

Same repository, same base, same validation as the ad-hoc run in `work/`, so the
two answers can be compared directly.
"""

from mergeset import analyze, fetch_pull_requests, pr_changes, markdown_report
from mergeset.report import html_report
from mergeset.validation import js_validation

REPO = "repo"
RECENT = {575, 576, 577, 579, 587, 602, 604, 616, 630, 631, 632, 633, 634, 636, 637}
OUT = "work/tool-run"
TITLE = "mergeset — cosmograph 2026-09-08"


def main():
    prs = [
        p
        for p in fetch_pull_requests("cosmograph-org/cosmograph", author="thorwhalen")
        if p["number"] in RECENT
    ]
    changes = list(pr_changes(REPO, prs, base="origin/main"))
    print(f"{len(changes)} candidate changes")

    analysis = analyze(
        REPO,
        changes,
        base="origin/main",
        validate=js_validation(
            build="pnpm run build:cosmos",
            test="pnpm run test --reporter=dot",
            lint="pnpm run lint:ci",
        ),
        log_path=f"{OUT}/evaluations.jsonl",
        worktree_root="<tool-worktrees>",
        reuse_worktree="<tool-eval-worktree>",
        on_event=lambda e, p: print(f"  · {e} {p}", flush=True),
    )
    md = markdown_report(analysis, title=TITLE)
    open(f"{OUT}/tool-REPORT.md", "w").write(md)
    open(f"{OUT}/tool-report.html", "w").write(html_report(analysis, title=TITLE))
    print(md)


if __name__ == "__main__":
    main()
