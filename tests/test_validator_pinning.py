"""A log row is about what was run, not only about the commits (#32).

Tier logs were keyed by repository and tier name, so editing a tier's command
reused the verdicts of the old one; the untiered log did the same when
``--validate-command`` changed. Rows now record a fingerprint of the validator
that judged them, and a log pinned to one validator does not count rows judged
by another. These tests change the command between two runs that share a log.
"""

import json

from mergeset.analysis import analyze
from mergeset.base import Evaluation, Verdict
from mergeset.log import EvaluationLog, MemoryLines
from mergeset.sources import branch_changes
from mergeset.validation import (
    ValidationStage,
    callable_validation,
    command_validation,
    fingerprint_of,
    flake_tolerant,
    merge_only_validation,
    pytest_validation,
    staged_validation,
)
import mergeset.cli as cli
from conftest import py_command

_PASS = "raise SystemExit(0)\n"
# Fails on any tree that contains feat-d's file.
_NO_D = "import os, sys\nsys.exit(1 if os.path.exists('new-d.txt') else 0)\n"


def _analyze(repo, log, validate, **kwargs):
    changes = list(branch_changes(repo, ["feat-b", "feat-d"], base="main"))
    return analyze(
        repo,
        changes,
        base="main",
        validate=validate,
        pairwise_preoracle=False,
        decompose=False,
        log=log,
        **kwargs,
    )


def _sets(analysis):
    return {tuple(sorted(s)) for s in analysis.maximal_sets}


def test_editing_a_tier_command_does_not_reuse_its_old_verdicts(repo, tmp_path):
    """The issue's repro: ``--tier u:true`` then ``--tier u:false``-ish."""

    def run(command):
        return cli.branches(
            ["feat-b", "feat-d"],
            repo=repo,
            base="main",
            tier=[f"u:{command}"],
            report_dir=str(tmp_path / "reports"),
            quiet=True,
        )

    first = run(py_command(tmp_path, "pass", _PASS))
    assert "Dropped: `feat-d`" not in first
    second = run(py_command(tmp_path, "nod", _NO_D))
    assert "Dropped: `feat-d`" in second, "the old command's passes answered"
    assert "judged by a different validator" in second


def test_editing_a_deep_tier_command_does_not_reuse_its_old_verdicts(repo, tmp_path):
    def run(deep):
        return cli.branches(
            ["feat-b", "feat-d"],
            repo=repo,
            base="main",
            tier=[f"screen:{py_command(tmp_path, 'pass', _PASS)}", f"deep:{deep}"],
            report_dir=str(tmp_path / "reports"),
            quiet=True,
        )

    assert "Dropped: `feat-d`" not in run(py_command(tmp_path, "pass2", _PASS))
    second = run(py_command(tmp_path, "nod", _NO_D))
    assert "Dropped: `feat-d`" in second
    assert "deep evaluation log holds" in second


def test_an_edited_validate_command_asks_a_new_question(repo, tmp_path):
    log = EvaluationLog(str(tmp_path / "eval.jsonl"))
    passing = command_validation(py_command(tmp_path, "pass", _PASS))
    first = _analyze(repo, log, passing)
    assert _sets(first) == {("feat-b", "feat-d")}

    strict = command_validation(py_command(tmp_path, "nod", _NO_D))
    second = _analyze(repo, EvaluationLog(str(tmp_path / "eval.jsonl")), strict)
    assert _sets(second) == {("feat-b",)}
    assert second.evaluations_this_run > 0
    assert second.log.other_validator, "the old rows are kept, and said to differ"
    assert any("judged by a different validator" in n for n in second.notes)


def test_the_same_command_still_makes_a_rerun_free(repo, tmp_path):
    path = str(tmp_path / "eval.jsonl")
    command = py_command(tmp_path, "pass", _PASS)
    _analyze(repo, EvaluationLog(path), command_validation(command))
    again = _analyze(repo, EvaluationLog(path), command_validation(command))
    assert again.evaluations_this_run == 0
    assert not again.log.stale and not again.log.unpinned


def test_rows_record_the_validator_that_judged_them(repo, tmp_path):
    validate = merge_only_validation()
    analysis = _analyze(repo, EvaluationLog(str(tmp_path / "e.jsonl")), validate)
    assert {e.validator for e in analysis.log.rows} == {fingerprint_of(validate)}
    on_disk = [json.loads(l) for l in open(tmp_path / "e.jsonl")]
    assert {d["validator"] for d in on_disk} == {fingerprint_of(validate)}


def _without_validator(path):
    """Rewrite a log as a release before #32 wrote it: commits, no validator."""
    rows = [json.loads(l) for l in open(path)]
    with open(path, "w") as f:
        for d in rows:
            del d["validator"]
            f.write(json.dumps(d, sort_keys=True) + "\n")


def test_rows_from_before_fingerprints_are_kept_and_not_trusted(repo, tmp_path):
    path = str(tmp_path / "eval.jsonl")
    _analyze(repo, EvaluationLog(path), merge_only_validation())
    _without_validator(path)
    before = open(path).read()

    again = _analyze(repo, EvaluationLog(path), merge_only_validation())
    assert again.evaluations_this_run > 0
    assert again.log.unpinned and not again.log.stale
    assert any("their validator" in n for n in again.notes)
    assert open(path).read().startswith(before), "never dropped"


def test_rows_from_before_fingerprints_can_be_adopted(repo, tmp_path):
    path = str(tmp_path / "eval.jsonl")
    _analyze(repo, EvaluationLog(path), merge_only_validation())
    _without_validator(path)
    again = _analyze(
        repo, EvaluationLog(path, trust_unpinned=True), merge_only_validation()
    )
    assert again.evaluations_this_run == 0
    assert not again.log.unpinned


def test_trust_never_adopts_a_row_recording_another_validator():
    log = EvaluationLog(MemoryLines(), trust_unpinned=True)
    row = Evaluation(
        frozenset("a"), Verdict.PASS, base_sha="B", heads={"a": "A"}, validator="x:1"
    )
    recorded = log.record(row)
    view = log.pinned(base="B", heads={"a": "A"}, validator="x:2")
    assert len(view) == 0 and view.stale == [recorded] and not view.unpinned


def test_a_validator_without_a_fingerprint_matches_on_commits_alone(repo, tmp_path):
    path = str(tmp_path / "eval.jsonl")
    validate = callable_validation(lambda worktree: True)
    assert fingerprint_of(validate) is None
    _analyze(repo, EvaluationLog(path), validate)
    again = _analyze(repo, EvaluationLog(path), callable_validation(lambda w: True))
    assert again.evaluations_this_run == 0


def test_a_user_validator_may_name_its_own_fingerprint(repo, tmp_path):
    path = str(tmp_path / "eval.jsonl")
    v1 = callable_validation(lambda worktree: True)
    v1.validator_fingerprint = "smoke-v1"
    _analyze(repo, EvaluationLog(path), v1)
    v2 = callable_validation(lambda worktree: True)
    v2.validator_fingerprint = "smoke-v2"
    again = _analyze(repo, EvaluationLog(path), v2)
    assert again.evaluations_this_run > 0


def test_what_changes_a_verdict_changes_the_fingerprint():
    f = fingerprint_of
    base = f(command_validation("make test"))
    assert base == f(command_validation("make test"))
    for other in (
        command_validation("make test", timeout=5),
        command_validation("make test", env={"CI": "1"}),
        flake_tolerant(command_validation("make test"), retries=2),
    ):
        assert f(other) not in (None, base)
    assert f(flake_tolerant(command_validation("x"), retries=1)) != f(
        flake_tolerant(command_validation("x"), retries=2)
    )
    assert f(pytest_validation()) != f(pytest_validation(args=["-x", "-m", "e2e"]))


def test_staged_fingerprints_follow_the_stages_not_their_setup_skipping():
    def staged(*stages):
        return fingerprint_of(staged_validation(list(stages)))

    test = ValidationStage("test", "make test")
    assert staged(test) == staged(ValidationStage("test", "make test"))
    assert staged(test) != staged(ValidationStage("test", "make check"))
    assert staged(test) != staged(ValidationStage("test", "make test", required=False))
    setup = ValidationStage("setup", "pip install .")
    skipping = ValidationStage("setup", "pip install .", fingerprint=lambda w: "x")
    assert staged(setup, test) == staged(skipping, test)


def test_what_cannot_say_what_it_runs_has_no_fingerprint():
    assert fingerprint_of(pytest_validation(select_paths=lambda w: [])) is None
    assert fingerprint_of(flake_tolerant(callable_validation(bool))) is None


def test_show_log_says_the_rows_mix_validators(repo, tmp_path):
    path = str(tmp_path / "eval.jsonl")
    _analyze(repo, EvaluationLog(path), command_validation(py_command(tmp_path, "p", _PASS)))
    _analyze(repo, EvaluationLog(path), merge_only_validation())
    assert "2 validators" in cli.show_log(log_path=path)
