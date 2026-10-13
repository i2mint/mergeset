"""A log row is about the commits that were merged, not about the ids (#23).

Re-running with the same ids over rewritten branches used to answer from the
old trees, confidently. These tests rewrite a branch between two runs that
share one log, and check the second run answers about the new head.
"""

import json
import os

from mergeset.analysis import analyze
from mergeset.base import Evaluation, Verdict
from mergeset.log import EvaluationLog, MemoryLines, Pins
from mergeset.sources import branch_changes
from mergeset.validation import merge_only_validation
from conftest import run


def _rewrite(repo, branch, filename, content):
    """Point ``branch`` at a fresh commit off main that writes ``filename``."""
    run(repo, "checkout", "-q", "-B", branch, "main")
    with open(os.path.join(repo, filename), "w") as f:
        f.write(content)
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", f"{branch} rewritten")
    run(repo, "checkout", "-q", "main")


def _analyze(repo, log_path, **kwargs):
    changes = list(branch_changes(repo, ["feat-a", "feat-c"], base="main"))
    return analyze(
        repo,
        changes,
        base="main",
        validate=merge_only_validation(),
        # The textual pre-oracle is recomputed every run and would find the
        # conflict on its own; the question here is what the *log* answers.
        pairwise_preoracle=False,
        # One search over the pair, so a row for the pair is actually written:
        # merge-only combines disjoint components without evaluating them.
        decompose=False,
        log=kwargs.pop("log", None) or EvaluationLog(log_path),
        **kwargs,
    )


def _sets(analysis):
    return {tuple(sorted(s)) for s in analysis.maximal_sets}


def test_a_rewritten_branch_is_not_answered_by_its_old_conflict(repo, tmp_path):
    """The issue's own report: a pair recorded as conflicting no longer does."""
    log_path = str(tmp_path / "eval.jsonl")
    first = _analyze(repo, log_path)
    assert ("feat-a", "feat-c") not in _sets(first)  # they edit the same line

    _rewrite(repo, "feat-c", "c.txt", "c, somewhere else now\n")
    second = _analyze(repo, log_path)
    assert _sets(second) == {("feat-a", "feat-c")}
    assert second.evaluations_this_run > 0, "the stale rows must not answer"


def test_a_rewritten_branch_is_not_answered_by_its_old_pass(repo, tmp_path):
    """The dangerous direction: a stale green reported as a validated set."""
    log_path = str(tmp_path / "eval.jsonl")
    _rewrite(repo, "feat-c", "c.txt", "c, harmless\n")
    first = _analyze(repo, log_path)
    assert _sets(first) == {("feat-a", "feat-c")}

    _rewrite(repo, "feat-c", "shared.txt", "line one\nCCC\nline three\n")
    second = _analyze(repo, log_path)
    assert ("feat-a", "feat-c") not in _sets(second)


def test_stale_rows_are_kept_and_said_to_be_kept(repo, tmp_path):
    log_path = str(tmp_path / "eval.jsonl")
    _analyze(repo, log_path)
    rows_before = open(log_path).read().splitlines()

    _rewrite(repo, "feat-c", "c.txt", "c, elsewhere\n")
    second = _analyze(repo, log_path)
    rows_after = open(log_path).read().splitlines()
    assert rows_after[: len(rows_before)] == rows_before, "nothing is rewritten"
    assert second.log.stale and len(second.log.rows) == len(rows_after)
    assert any("other commits" in n for n in second.notes)


def test_a_moved_base_invalidates_every_row(repo, tmp_path):
    log_path = str(tmp_path / "eval.jsonl")
    _analyze(repo, log_path)
    run(repo, "checkout", "-q", "main")
    with open(os.path.join(repo, "moved.txt"), "w") as f:
        f.write("main moved on\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "main moves")
    second = _analyze(repo, log_path)
    assert second.evaluations_this_run > 0
    assert len(second.log.stale) == len(second.log.rows) - len(second.log)


def test_unchanged_heads_still_make_a_rerun_free(repo, tmp_path):
    log_path = str(tmp_path / "eval.jsonl")
    _analyze(repo, log_path)
    again = _analyze(repo, log_path)
    assert again.evaluations_this_run == 0
    assert not again.log.stale and not again.log.unpinned


def _legacy_rows(path, rows):
    """Write rows in the pre-#23 format: no ``base_sha``, no ``heads``."""
    with open(path, "w") as f:
        for subset, verdict in rows:
            d = Evaluation(frozenset(subset), Verdict(verdict)).to_jdict()
            del d["base_sha"], d["heads"]
            f.write(json.dumps(d, sort_keys=True) + "\n")


def test_a_legacy_log_is_read_kept_and_not_trusted_by_default(repo, tmp_path):
    log_path = str(tmp_path / "old.jsonl")
    # A stale green from before pinning: the pair really conflicts.
    _legacy_rows(log_path, [((), "pass"), (("feat-a", "feat-c"), "pass")])
    legacy = open(log_path).read().splitlines()

    analysis = _analyze(repo, log_path)
    assert ("feat-a", "feat-c") not in _sets(analysis)
    assert len(analysis.log.unpinned) == 2
    assert any("trust_unpinned" in n for n in analysis.notes)
    assert open(log_path).read().splitlines()[:2] == legacy, "never dropped"


def test_a_legacy_log_can_be_adopted_when_heads_have_not_moved(repo, tmp_path):
    log_path = str(tmp_path / "old.jsonl")
    _legacy_rows(
        log_path,
        [
            ((), "pass"),
            (("feat-a",), "pass"),
            (("feat-c",), "pass"),
            (("feat-a", "feat-c"), "fail"),
        ],
    )
    log = EvaluationLog(log_path, trust_unpinned=True)
    analysis = _analyze(repo, log_path, log=log)
    assert analysis.evaluations_this_run == 0, "every answer came from the old rows"
    assert ("feat-a", "feat-c") not in _sets(analysis)
    assert not analysis.log.unpinned


def test_rows_record_the_shas_they_were_merged_at(repo, tmp_path):
    analysis = _analyze(repo, str(tmp_path / "eval.jsonl"))
    sha = run(repo, "rev-parse", "feat-c").strip()
    rows = [e for e in analysis.log.rows if "feat-c" in e.subset]
    assert rows and all(e.heads["feat-c"] == sha for e in rows)
    assert all(e.base_sha == analysis.base_sha for e in analysis.log.rows)


def test_a_row_holding_a_change_not_in_play_does_not_count():
    """Its head for that change is unchecked, so it answers nothing here.

    Counting it once let an "established" fallback set recommend ``x`` -- not
    a candidate -- and reported two heads of ``x`` as a monotonicity violation.
    """
    log = EvaluationLog(MemoryLines())
    log.record(
        Evaluation(
            frozenset("ax"), Verdict.FAIL, base_sha="B", heads={"a": "A1", "x": "X0"}
        )
    )
    log.record(
        Evaluation(
            frozenset("abx"),
            Verdict.PASS,
            base_sha="B",
            heads={"a": "A1", "b": "B1", "x": "X1"},
        )
    )
    view = log.pinned(base="B", heads={"a": "A1", "b": "B1"})
    assert not view.monotonicity_violations()
    assert not view.maximal_passing_sets()
    assert len(view.stale) == 2


def test_pins_given_at_construction_scope_the_log():
    lines = MemoryLines()
    EvaluationLog(lines).pin(base="B", heads={"a": "A1"}).record(
        Evaluation(frozenset("a"), Verdict.FAIL)
    )
    assert EvaluationLog(lines, pins=Pins("B", {"a": "A1"})).exact(frozenset("a"))
    assert not EvaluationLog(lines, pins=Pins("B", {"a": "A2"})).exact(frozenset("a"))


def test_every_tier_log_is_pinned_not_only_the_screens(repo, tmp_path):
    """A deep tier's cached FAIL must not outlive the head it was about."""
    from mergeset.tiers import Tier, analyze_tiered
    from test_tiers import _changes, _stage_validator

    deep = _stage_validator(
        tmp_path,
        "deep",
        "import os, sys\n" "sys.exit(1 if os.path.exists('new-d.txt') else 0)\n",
    )

    def tiered():
        return analyze_tiered(
            repo,
            _changes(repo, ["feat-b", "feat-d"]),
            base="main",
            tiers=[Tier("screen", merge_only_validation()), Tier("deep", deep)],
            pairwise_preoracle=False,
            use_ci_status=False,
        )

    assert tiered().maximal_sets == [frozenset({"feat-b"})]
    _rewrite(repo, "feat-d", "d-renamed.txt", "d\n")
    again = tiered()
    assert again.maximal_sets == [frozenset({"feat-b", "feat-d"})]
    assert again.verified_tier(frozenset({"feat-b", "feat-d"})) == "deep"
    assert again.logs["deep"].stale


def _move_during_the_run(repo, branch, filename, content):
    """A ``weight`` callback that rewrites ``branch`` once heads are resolved.

    ``analyze`` resolves heads, then weighs the changes, then does everything
    else. Moving a branch from inside ``weight`` is a branch moving mid-run:
    every later step must still see the commit that was resolved.
    """
    moved = []

    def weight(change):
        if not moved:
            moved.append(True)
            _rewrite(repo, branch, filename, content)
        return 1.0

    return weight


def test_a_branch_moving_mid_run_does_not_reach_the_pre_oracles(repo):
    changes = list(branch_changes(repo, ["feat-a", "feat-c"], base="main"))
    analysis = analyze(
        repo,
        changes,
        base="main",
        validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
        weight=_move_during_the_run(repo, "feat-c", "c.txt", "elsewhere\n"),
    )
    # feat-c as resolved edits shared.txt, and conflicts with feat-a there.
    assert analysis.files_by_change["feat-c"] == ["shared.txt"]
    assert [(a, b) for a, b, _ in analysis.textual_conflicts] == [("feat-a", "feat-c")]


def test_a_branch_moving_mid_run_does_not_reach_the_oracle(repo):
    changes = list(branch_changes(repo, ["feat-a", "feat-c"], base="main"))
    analysis = analyze(
        repo,
        changes,
        base="main",
        validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
        pairwise_preoracle=False,
        decompose=False,
        weight=_move_during_the_run(repo, "feat-c", "c.txt", "elsewhere\n"),
    )
    assert ("feat-a", "feat-c") not in _sets(analysis)


def test_a_branch_moving_mid_run_does_not_reach_a_deep_tier(repo, tmp_path):
    from mergeset.tiers import Tier, analyze_tiered
    from test_tiers import _changes, _stage_validator

    deep = _stage_validator(
        tmp_path,
        "deep",
        "import os, sys\n" "sys.exit(1 if os.path.exists('new-d.txt') else 0)\n",
    )
    result = analyze_tiered(
        repo,
        _changes(repo, ["feat-b", "feat-d"]),
        base="main",
        tiers=[Tier("screen", merge_only_validation()), Tier("deep", deep)],
        pairwise_preoracle=False,
        use_ci_status=False,
        weight=_move_during_the_run(repo, "feat-d", "d-renamed.txt", "d\n"),
    )
    assert result.maximal_sets == [frozenset({"feat-b"})]


def test_an_integration_branch_holds_the_validated_commits(repo):
    from mergeset.cli import _integration_branches

    changes = list(branch_changes(repo, ["feat-b", "feat-c"], base="main"))
    analysis = analyze(
        repo,
        changes,
        base="main",
        validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
        weight=_move_during_the_run(repo, "feat-c", "c.txt", "elsewhere\n"),
    )
    assert _sets(analysis) == {("feat-b", "feat-c")}
    (line,) = _integration_branches(analysis)
    name = line.split("`")[1]
    files = run(repo, "ls-tree", "--name-only", name).split()
    assert "c.txt" not in files
    assert "CCC" in run(repo, "show", f"{name}:shared.txt")


def _lagging_stack(repo):
    """pr2 stacked on pr1 by metadata, but pr1 moved on and pr2 was not rebased.

    pr1's new commit adds ``broken.txt``, which :func:`_no_broken` rejects.
    """
    from mergeset.base import Change

    def commit(name, text):
        with open(os.path.join(repo, name), "w") as f:
            f.write(text)
        run(repo, "add", "-A")
        run(repo, "commit", "-qm", name)

    run(repo, "checkout", "-q", "-b", "stack-a", "main")
    commit("a1.txt", "a1\n")
    run(repo, "checkout", "-q", "-b", "stack-b")
    commit("b1.txt", "b1\n")
    run(repo, "checkout", "-q", "stack-a")
    commit("broken.txt", "a2\n")
    run(repo, "checkout", "-q", "main")
    return [
        Change(
            "pr1",
            "stack-a",
            "main",
            "pr",
            meta={"head_ref": "stack-a", "base_ref": "main"},
        ),
        Change(
            "pr2",
            "stack-b",
            "stack-a",
            "pr",
            meta={"head_ref": "stack-b", "base_ref": "stack-a"},
        ),
    ]


def _no_broken():
    from mergeset.validation import callable_validation

    return callable_validation(
        lambda wt: not os.path.exists(os.path.join(wt, "broken.txt"))
    )


def test_a_stacked_child_that_lags_its_parent_is_not_pinned_to_the_parent(repo):
    """The child's tree does not contain the parent's new head, so merge both."""
    analysis = analyze(
        repo,
        _lagging_stack(repo),
        base="main",
        validate=_no_broken(),
        log=EvaluationLog(MemoryLines()),
        use_ci_status=False,
    )
    assert analysis.stacks == {"pr2": "pr1"} and not analysis.merged_through
    # pr1 as it is now is broken, and pr2 cannot go without it.
    assert _sets(analysis) == {()}
    assert any("does not contain" in n for n in analysis.notes)


def test_a_deep_tier_merges_the_parent_a_lagging_child_lacks(repo, tmp_path):
    from mergeset.tiers import Tier, analyze_tiered

    result = analyze_tiered(
        repo,
        _lagging_stack(repo),
        base="main",
        tiers=[Tier("screen", merge_only_validation()), Tier("deep", _no_broken())],
        use_ci_status=False,
    )
    assert result.maximal_sets == [frozenset()]


def test_the_merge_plan_names_a_parent_a_lagging_child_lacks(repo):
    """Following "merge pr2, pr1 comes along" would land pr1's old head."""
    analysis = analyze(
        repo,
        _lagging_stack(repo),
        base="main",
        validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
        use_ci_status=False,
    )
    (plan,) = analysis.merge_plan()
    assert sorted(plan["merge"]) == ["pr1", "pr2"]


def test_a_log_handed_to_two_analyses_is_not_rescoped_under_the_first(repo, tmp_path):
    log = EvaluationLog(str(tmp_path / "eval.jsonl"))
    first = _analyze(repo, None, log=log)
    _rewrite(repo, "feat-c", "c.txt", "elsewhere\n")
    _analyze(repo, None, log=log)
    assert log.pins is None, "the caller's log is not pinned under it"
    assert ("feat-a", "feat-c") not in _sets(first)
    assert first.log.exact(frozenset({"feat-a", "feat-c"})).verdict is Verdict.FAIL


def test_trust_unpinned_reaches_analyze(repo, tmp_path):
    log_path = str(tmp_path / "old.jsonl")
    _legacy_rows(log_path, [((), "pass")])
    analysis = _analyze(repo, log_path, trust_unpinned=True)
    assert not analysis.log.unpinned
    assert analysis.log.exact(frozenset()) is not None


def test_trust_unpinned_reaches_every_tier(repo):
    from mergeset.tiers import Tier, analyze_tiered, tier_lines

    for tier in ("screen", "deep"):
        EvaluationLog(tier_lines(repo, tier)).record(
            Evaluation(frozenset(), Verdict.PASS)  # unpinned, as an old log
        )

    def tiered(**kwargs):
        return analyze_tiered(
            repo,
            list(branch_changes(repo, ["feat-b"], base="main")),
            base="main",
            tiers=[
                Tier("screen", merge_only_validation()),
                Tier("deep", merge_only_validation()),
            ],
            **kwargs,
        )

    assert tiered().logs["deep"].unpinned
    trusted = tiered(trust_unpinned=True)
    assert not trusted.logs["deep"].unpinned
    assert not trusted.logs["screen"].unpinned


def test_trusted_old_rows_still_speak_only_for_changes_in_play():
    log = EvaluationLog(MemoryLines())
    log.record(Evaluation(frozenset("abx"), Verdict.PASS))
    view = log.pinned(base="B", heads={"a": "A1", "b": "B1"}, trust_unpinned=True)
    assert not view.maximal_passing_sets()
    assert len(view.unpinned) == 1


def test_trust_unpinned_takes_effect_when_changed_after_reading():
    log = EvaluationLog(MemoryLines())
    log.record(Evaluation(frozenset("a"), Verdict.PASS))
    log.pin(base="B", heads={"a": "A1"})
    assert len(log) == 0
    log.trust_unpinned = True
    assert len(log) == 1


def test_every_tier_reports_and_reuses_only_the_rows_that_count(repo, tmp_path):
    """The screen's pinned view is the one kept, and spent sums only its rows."""
    from mergeset.tiers import Tier, analyze_tiered

    def tiered():
        return analyze_tiered(
            repo,
            list(branch_changes(repo, ["feat-a", "feat-c"], base="main")),
            base="main",
            tiers=[
                Tier("screen", merge_only_validation()),
                Tier("deep", merge_only_validation()),
            ],
            pairwise_preoracle=False,
            decompose=False,
        )

    tiered()
    _rewrite(repo, "feat-c", "c.txt", "elsewhere\n")
    result = tiered()
    for name, log in result.logs.items():
        assert log.pins is not None and log.stale, name
        assert result.spent[name] == sum(e.duration or 0 for e in log), name
        assert result.spent[name] < sum(e.duration or 0 for e in log.rows), name


def test_the_cli_passes_trust_unpinned_log_through(repo, monkeypatch):
    import mergeset.cli as cli

    seen = {}

    def fake_analyze(*args, **kwargs):
        seen.update(kwargs)
        raise ValueError("stop here")

    monkeypatch.setattr(cli, "_analyze", fake_analyze)
    cli.branches(
        ["feat-a"], repo=repo, base="main", merge_only=True, trust_unpinned_log=True
    )
    assert seen.get("trust_unpinned") is True
