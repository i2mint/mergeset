"""show-log says when rows were merged with different resolvers (#45).

A log holding an assisted PASS (with a resolver) and a conflict FAIL (without
one) for the same set used to print a bare monotonicity violation, with no hint
that the two rows answer different questions (ADR 0033).
"""

from mergeset import cli
from mergeset.base import Evaluation, MergeOutcome, Stage, Verdict
from mergeset.log import EvaluationLog

_PAIR = frozenset({"a", "c"})


def _conflict(subset=_PAIR, resolver="none"):
    return Evaluation(
        subset,
        Verdict.FAIL,
        stage=Stage.MERGE,
        merge=MergeOutcome(False, "conflict", conflicting_files=["shared.txt"]),
        resolver=resolver,
    )


def _assisted(subset=_PAIR, resolver="claude-code:1"):
    return Evaluation(
        subset,
        Verdict.PASS,
        stage=Stage.VALIDATE,
        merge=MergeOutcome(True, assisted=True),
        resolver=resolver,
    )


def _clean(subset, verdict, resolver):
    return Evaluation(
        subset,
        verdict,
        stage=Stage.VALIDATE,
        merge=MergeOutcome(True),
        resolver=resolver,
    )


def _show(tmp_path, *rows):
    path = str(tmp_path / "eval.jsonl")
    log = EvaluationLog(path)
    for row in rows:
        log.record(row)
    return cli.show_log(log_path=path)


def test_the_issues_log_names_the_resolvers_not_a_violation(tmp_path):
    out = _show(tmp_path, _assisted(), _conflict())
    assert "2 conflict resolvers" in out
    assert "monotonicity violation" not in out
    assert (
        "failed with no conflict resolver, passed with resolver claude-code:1" in out
    )
    assert out.count("bad but") == 1


def test_a_conflict_inside_a_set_another_resolver_merged(tmp_path):
    out = _show(tmp_path, _conflict(), _assisted(frozenset({"a", "c", "d"})))
    assert "monotonicity violation" not in out
    assert "answer different questions" in out


def test_the_same_resolver_declining_and_merging_is_still_a_violation(tmp_path):
    out = _show(
        tmp_path,
        _assisted(resolver="claude-code:1"),
        _conflict(resolver="claude-code:1"),
    )
    assert "conflict resolvers" not in out
    assert "monotonicity violation" in out


def test_a_validation_failure_is_still_a_violation(tmp_path):
    out = _show(tmp_path, _assisted(), _clean(_PAIR, Verdict.FAIL, "none"))
    assert "monotonicity violation" in out


def test_clean_rows_under_different_resolvers_are_not_a_mix(tmp_path):
    out = _show(
        tmp_path,
        _clean(frozenset("a"), Verdict.PASS, "none"),
        _clean(frozenset("c"), Verdict.PASS, "claude-code:1"),
    )
    assert "conflict resolvers" not in out


def test_an_old_conflict_is_counted_as_no_resolver_not_as_a_mix(tmp_path):
    out = _show(tmp_path, _conflict(resolver=None), _conflict(frozenset("b")))
    assert "conflict resolvers" not in out


def test_an_old_assisted_row_counts_as_one_more(tmp_path):
    out = _show(tmp_path, _assisted(resolver=None), _conflict(frozenset("b")))
    assert "2 conflict resolvers" in out


def test_an_old_row_explains_no_violation(tmp_path):
    out = _show(tmp_path, _assisted(), _conflict(resolver=None))
    assert "! monotonicity violation" in out


def test_a_resolution_that_failed_validation_under_another_resolver(tmp_path):
    failed = Evaluation(
        _PAIR,
        Verdict.FAIL,
        stage=Stage.VALIDATE,
        merge=MergeOutcome(True, assisted=True),
        resolver="claude-code:2",
    )
    out = _show(tmp_path, _assisted(), failed)
    assert "monotonicity violation" not in out
    assert "failed with resolver claude-code:2" in out


def test_each_pair_is_printed_once(tmp_path):
    out = _show(tmp_path, _assisted(), _assisted(), _conflict(), _conflict())
    assert out.count("bad but") == 1
