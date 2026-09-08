"""Git-level behaviour, against real throwaway repositories."""

import os
import subprocess
import textwrap

import pytest

from mergeset.analysis import analyze
from mergeset.base import Verdict
from mergeset.gitops import (
    changed_files,
    check_git_capability,
    merge_sequence,
    merged_worktree,
    pairwise_textual_conflicts,
    singleton_textual_conflicts,
    textual_conflict,
)
from mergeset.log import EvaluationLog, MemoryLines
from mergeset.report import html_report, markdown_report
from mergeset.sources import branch_changes
from mergeset.validation import ValidationStage, merge_only_validation, staged_validation
from conftest import run


def test_capability_check_passes_on_a_modern_git():
    check_git_capability()


def test_changed_files_reports_what_a_branch_touched(repo):
    assert changed_files(repo, "main", "feat-a") == ["shared.txt"]
    assert changed_files(repo, "main", "feat-b") == ["other.txt"]


def test_disjoint_branches_do_not_conflict(repo):
    assert textual_conflict(repo, "main", "feat-a", "feat-b") is None


def test_same_line_edits_conflict_and_name_the_file(repo):
    assert textual_conflict(repo, "main", "feat-a", "feat-c") == ["shared.txt"]


def test_merge_sequence_produces_a_real_commit(repo):
    result = merge_sequence(repo, "main", [("a", "feat-a"), ("b", "feat-b")])
    assert result.ok and result.commit
    tree = run(repo, "show", "--stat", "--oneline", result.commit)
    assert "shared.txt" in run(repo, "diff", "--name-only", "main", result.commit)


def test_merge_sequence_reports_which_change_broke_it(repo):
    result = merge_sequence(repo, "main", [("a", "feat-a"), ("c", "feat-c")])
    assert not result.ok
    assert result.order[-1] == "c", "the last merged change is the culprit"
    assert result.conflicting_files == ["shared.txt"]


def test_merge_tree_chains_through_base_rather_than_pairwise(repo):
    """A branch that is behind main must not manufacture conflicts.

    `git merge-tree A B` uses merge-base(A, B). When one branch is stale, that
    is an older commit than the base we care about, and main's own commits get
    reported as conflicts. Chaining through base is what avoids it.
    """
    # Advance main well past feat-a's cut point, touching a third file.
    run(repo, "checkout", "-q", "main")
    with open(os.path.join(repo, "moved-on.txt"), "w") as f:
        f.write("main moved on\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "main moves on")
    # feat-a is now stale; feat-b was cut from the same old point.
    assert textual_conflict(repo, "main", "feat-a", "feat-b") is None
    assert textual_conflict(repo, "main", "feat-a", "feat-c") == ["shared.txt"]


def test_singleton_preoracle_finds_a_change_that_cannot_land(repo):
    run(repo, "checkout", "-q", "main")
    with open(os.path.join(repo, "shared.txt"), "w") as f:
        f.write("line one\nMAIN MOVED\nline three\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "main edits the same line")
    found = dict(singleton_textual_conflicts(repo, "main", {"a": "feat-a", "b": "feat-b"}))
    assert set(found) == {"a"}
    assert found["a"] == ["shared.txt"]


def test_merged_worktree_gives_a_tree_with_every_change(repo):
    with merged_worktree(repo, "main", [("a", "feat-a"), ("b", "feat-b")]) as (path, outcome):
        assert outcome.ok and path
        assert open(os.path.join(path, "shared.txt")).read().splitlines()[1] == "AAA"
        assert open(os.path.join(path, "other.txt")).read().strip() == "changed by b"


def test_merged_worktree_cleans_up_after_itself(repo):
    with merged_worktree(repo, "main", [("a", "feat-a")]) as (path, _):
        kept = path
    assert not os.path.exists(kept)
    assert "wt-" not in run(repo, "worktree", "list")


def test_conflicted_set_never_creates_a_worktree(repo):
    with merged_worktree(repo, "main", [("a", "feat-a"), ("c", "feat-c")]) as (path, outcome):
        assert path is None
        assert not outcome.ok
        assert outcome.conflicting_files == ["shared.txt"]


def test_pairwise_preoracle_finds_exactly_the_real_pair(repo):
    heads = {"a": "feat-a", "b": "feat-b", "c": "feat-c", "d": "feat-d"}
    found = {(a, b) for a, b, _ in pairwise_textual_conflicts(repo, "main", heads)}
    assert found == {("a", "c")}


def test_end_to_end_merge_only_analysis(repo, tmp_path):
    changes = list(branch_changes(repo, ["feat-a", "feat-b", "feat-c", "feat-d"], base="main"))
    analysis = analyze(
        repo, changes, base="main",
        validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
    )
    sets = {tuple(sorted(s)) for s in analysis.maximal_sets}
    assert sets == {
        ("feat-a", "feat-b", "feat-d"),
        ("feat-b", "feat-c", "feat-d"),
    }
    # The conflicting pair was found by merge-tree, so it cost no evaluation.
    assert analysis.textual_conflicts
    # merge-only declares itself component-local, so the components combine
    # without a global re-check: 1 baseline + one run per component branch.
    assert analysis.evaluations <= 5


def test_end_to_end_with_a_failing_validation(repo):
    """A set that merges cleanly can still fail — that is the whole point."""
    changes = list(branch_changes(repo, ["feat-a", "feat-b", "feat-d"], base="main"))
    analysis = analyze(
        repo, changes, base="main",
        # "b and d together are forbidden", expressible only by running something
        validate=staged_validation([
            ValidationStage("test", "test ! \\( -f other.txt -a -f new-d.txt \\) "
                                    "|| ! grep -q 'changed by b' other.txt"),
        ]),
        log=EvaluationLog(MemoryLines()),
        decompose=False,
    )
    sets = {tuple(sorted(s)) for s in analysis.maximal_sets}
    assert ("feat-b", "feat-d") not in sets
    assert any("feat-b" in s for s in sets) and any("feat-d" in s for s in sets)


def test_reports_render_from_an_analysis(repo):
    changes = list(branch_changes(repo, ["feat-a", "feat-b", "feat-c"], base="main"))
    analysis = analyze(
        repo, changes, base="main", validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
    )
    md = markdown_report(analysis)
    assert "Recommended merge plans" in md and "feat-a" in md
    html = html_report(analysis)
    assert html.lstrip().startswith("<!doctype html>")
    assert "__DATA__" not in html and "__TITLE__" not in html


def test_evaluation_log_makes_a_second_run_free(repo, tmp_path):
    log_path = str(tmp_path / "eval.jsonl")
    changes = list(branch_changes(repo, ["feat-a", "feat-b", "feat-c"], base="main"))
    first = analyze(repo, changes, base="main", validate=merge_only_validation(), log_path=log_path)
    second = analyze(repo, changes, base="main", validate=merge_only_validation(), log_path=log_path)
    assert second.evaluations == 0, "the log should have answered everything"
    assert {tuple(sorted(s)) for s in first.maximal_sets} == {
        tuple(sorted(s)) for s in second.maximal_sets
    }
