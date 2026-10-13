"""A row whose outcome a resolver decided answers only runs that resolve alike (#34).

Rows were pinned to commits (#23) and to the validator (#32), not to how the
set was merged. A set that merges only with a resolver recorded an assisted
PASS, and a later run of the same log without the resolver reused it, although
without the resolver the set is a textual conflict; the reverse reused a
conflict where the resolver would have merged. Rows now record the resolver,
and only rows whose outcome it decided (an assisted merge, a conflict left
standing) are pinned to it: a clean merge is the same tree either way.
"""

import json

from mergeset.analysis import analyze
from mergeset.base import Evaluation, MergeOutcome, Verdict
from mergeset.log import EvaluationLog, MemoryLines
from mergeset.oracle import claude_code_resolver, resolver_fingerprint_of
from mergeset.tiers import Tier, analyze_tiered
from mergeset.validation import command_validation
from conftest import py_command
from test_resolution import _changes, _scripted_resolver

_PASS = "raise SystemExit(0)\n"
_PAIR = frozenset({"feat-a", "feat-c"})  # conflicts in shared.txt


def _analyze(repo, tmp_path, names, resolver=None, log=None):
    return analyze(
        repo,
        _changes(names),
        base="main",
        validate=command_validation(py_command(tmp_path, "pass", _PASS)),
        resolver=resolver,
        pairwise_preoracle=False,
        decompose=False,
        log=log or EvaluationLog(str(tmp_path / "eval.jsonl")),
    )


def test_an_assisted_pass_does_not_answer_a_run_without_the_resolver(repo, tmp_path):
    """The issue's repro."""
    calls = []
    first = _analyze(repo, tmp_path, ["feat-a", "feat-c"], _scripted_resolver(calls))
    assert first.maximal_sets == [_PAIR]
    second = _analyze(repo, tmp_path, ["feat-a", "feat-c"])
    assert _PAIR not in second.maximal_sets, "the assisted PASS answered"
    assert second.log.other_resolver
    assert any("resolves them differently" in n for n in second.notes)


def test_a_conflict_without_a_resolver_does_not_answer_a_run_with_one(repo, tmp_path):
    first = _analyze(repo, tmp_path, ["feat-a", "feat-c"])
    assert _PAIR not in first.maximal_sets
    calls = []
    second = _analyze(repo, tmp_path, ["feat-a", "feat-c"], _scripted_resolver(calls))
    assert second.maximal_sets == [_PAIR], "the unresolved conflict answered"
    assert calls, "the resolver was asked"


def test_a_clean_merge_answers_every_resolver(repo, tmp_path):
    _analyze(repo, tmp_path, ["feat-b", "feat-d"], _scripted_resolver([]))
    again = _analyze(repo, tmp_path, ["feat-b", "feat-d"])
    assert again.evaluations_this_run == 0
    assert not again.log.stale and not again.log.unpinned


def test_a_conflict_a_resolver_declined_answers_a_run_without_one(repo, tmp_path):
    def declining(worktree, files):
        return False, "no"

    _analyze(repo, tmp_path, ["feat-a", "feat-c"], declining)
    again = _analyze(repo, tmp_path, ["feat-a", "feat-c"])
    assert again.evaluations_this_run == 0
    assert _PAIR not in again.maximal_sets


def test_the_same_resolver_still_makes_a_rerun_free(repo, tmp_path):
    calls = []
    _analyze(repo, tmp_path, ["feat-a", "feat-c"], _scripted_resolver(calls))
    again = _analyze(repo, tmp_path, ["feat-a", "feat-c"], _scripted_resolver(calls))
    assert again.evaluations_this_run == 0
    assert len(calls) == 1


def test_tiers_do_not_reuse_an_assisted_pass_without_the_resolver(repo, tmp_path):
    def tiered(**kwargs):
        ok = command_validation(py_command(tmp_path, "pass", _PASS))
        return analyze_tiered(
            repo,
            _changes(["feat-a", "feat-c"]),
            base="main",
            tiers=[Tier("screen", ok), Tier("deep", ok)],
            pairwise_preoracle=False,
            decompose=False,
            use_ci_status=False,
            **kwargs,
        )

    assert tiered(resolver=_scripted_resolver([])).maximal_sets == [_PAIR]
    assert _PAIR not in tiered().maximal_sets


def _old_row(row):
    """``row`` as a release before #34 wrote it: no ``resolver`` key."""
    d = row.to_jdict()
    del d["resolver"]
    return Evaluation.from_jdict(json.loads(json.dumps(d)))


def _log_with(row, resolver):
    log = EvaluationLog(MemoryLines()).pin(
        base="B", heads={"a": "A1", "b": "B1"}, validator="v", resolver=resolver
    )
    log._rows.append(row)
    log._view_of = -1
    return log


def test_rows_from_before_34_are_unpinned_only_where_the_resolver_mattered():
    pinned = dict(base_sha="B", heads={"a": "A1", "b": "B1"}, validator="v")
    ab = frozenset("ab")
    assisted = _old_row(
        Evaluation(ab, Verdict.PASS, merge=MergeOutcome(True, assisted=True), **pinned)
    )
    conflict = _old_row(
        Evaluation(ab, Verdict.FAIL, merge=MergeOutcome(False, "conflict"), **pinned)
    )
    clean = _old_row(Evaluation(ab, Verdict.PASS, merge=MergeOutcome(True), **pinned))
    assert assisted.resolver is None
    # An old assisted row: which resolver made it is unknown.
    assert _log_with(assisted, "claude-code:1").unpinned
    assert not _log_with(assisted, "none").known(ab).verdict
    # An old conflict stands for a run without a resolver, whoever recorded it.
    assert _log_with(conflict, "none").known(ab).verdict is Verdict.FAIL
    assert _log_with(conflict, "claude-code:1").unpinned
    # A clean merge never depended on it.
    assert _log_with(clean, "claude-code:1").known(ab).verdict is Verdict.PASS


def test_rows_record_the_resolver_and_read_it_back(repo, tmp_path):
    _analyze(repo, tmp_path, ["feat-a", "feat-c"], _scripted_resolver([]))
    rows = [
        json.loads(line)
        for line in (tmp_path / "eval.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert {r["resolver"] for r in rows} == {"unknown"}  # no fingerprint set
    assert Evaluation.from_jdict(rows[-1]).resolver == "unknown"


def test_claude_resolver_fingerprint_follows_what_decides_its_answers():
    assert resolver_fingerprint_of(claude_code_resolver()) == resolver_fingerprint_of(
        claude_code_resolver()
    )
    assert resolver_fingerprint_of(
        claude_code_resolver(timeout=10)
    ) != resolver_fingerprint_of(claude_code_resolver())
    assert resolver_fingerprint_of(None) == "none"


def test_trusting_old_rows_never_adopts_an_assisted_pass_without_a_resolver():
    """Review finding: ``trust_unpinned`` must not bring #34 back."""
    ab = frozenset("ab")
    assisted = _old_row(
        Evaluation(
            ab,
            Verdict.PASS,
            merge=MergeOutcome(True, assisted=True),
            base_sha="B",
            heads={"a": "A1", "b": "B1"},
            validator="v",
        )
    )
    log = _log_with(assisted, "none")
    log.trust_unpinned = True
    assert log.known(ab).verdict is None
    assert log.other_resolver
