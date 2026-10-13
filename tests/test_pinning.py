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


def test_a_row_about_a_change_not_in_play_still_informs_the_closure():
    """A passing {a, b, x} says {a, b} is good, whatever x was at."""
    log = EvaluationLog(MemoryLines())
    log.record(
        Evaluation(
            frozenset("abx"),
            Verdict.PASS,
            base_sha="B",
            heads={"a": "A1", "b": "B1", "x": "X0"},
        )
    )
    log.pin(base="B", heads={"a": "A1", "b": "B1"})
    assert log.known(frozenset("ab")).verdict is Verdict.PASS
    log.pin(base="B", heads={"a": "A1", "b": "B2"})
    assert log.known(frozenset("ab")).verdict is None


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
