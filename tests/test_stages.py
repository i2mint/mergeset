"""Per-stage timings reach the evaluation log, and read back (#17).

A staged validator reports each stage's exit code separately; the log used to
keep only the total time, so the one number a cost model most wants -- how much
of an evaluation was the dependency install, and was it skipped -- was gone.
"""

import json

from mergeset.analysis import analyze
from mergeset.base import Evaluation, StageRun, ValidationOutcome, Verdict
from mergeset.log import EvaluationLog, MemoryLines
from mergeset.report import markdown_report
from mergeset.sources import branch_changes
from mergeset.validation import ValidationStage, file_fingerprint, staged_validation
from conftest import py_command


def _sleeper(tmp_path, name, seconds, code=0):
    return py_command(
        tmp_path, name, f"import sys, time; time.sleep({seconds}); sys.exit({code})"
    )


def test_each_stage_records_its_own_time_and_exit_code(tmp_path):
    validate = staged_validation(
        [
            ValidationStage("setup", _sleeper(tmp_path, "setup", 0.3)),
            ValidationStage("test", _sleeper(tmp_path, "test", 0.0)),
        ]
    )
    outcome = validate(str(tmp_path))
    assert [s.name for s in outcome.stages] == ["setup", "test"]
    setup, test = outcome.stages
    assert setup.duration >= 0.3 > test.duration
    assert (setup.returncode, test.returncode) == (0, 0)
    assert sum(outcome.stage_seconds.values()) <= outcome.duration


def test_a_fingerprint_skip_is_recorded_as_a_skip(tmp_path):
    (tmp_path / "lock").write_text("v1")
    validate = staged_validation(
        [
            ValidationStage("setup", "exit 0", fingerprint=file_fingerprint("lock")),
            ValidationStage("test", "exit 0"),
        ]
    )
    validate(str(tmp_path))
    second = validate(str(tmp_path))
    assert second.stages[0] == StageRun("setup", skipped=True)
    assert "setup" not in second.stage_seconds
    assert not second.stages[1].skipped


def test_stages_after_a_required_failure_are_not_recorded_as_run(tmp_path):
    validate = staged_validation(
        [
            ValidationStage("build", "exit 3"),
            ValidationStage("test", "exit 0"),
        ]
    )
    outcome = validate(str(tmp_path))
    assert [(s.name, s.returncode) for s in outcome.stages] == [("build", 3)]


def test_stages_survive_the_log_and_old_rows_read_without_them(tmp_path):
    path = tmp_path / "eval.jsonl"
    stages = (StageRun("setup", skipped=True), StageRun("test", 6.0, 0))
    log = EvaluationLog(str(path))
    log.record(
        Evaluation(
            frozenset("a"),
            Verdict.PASS,
            validation=ValidationOutcome(True, duration=6.0, stages=stages),
        )
    )
    old = Evaluation(
        frozenset("b"), Verdict.PASS, validation=ValidationOutcome(True)
    ).to_jdict()
    del old["validation_stages"]  # a row written before #17
    with open(path, "a") as f:
        f.write(json.dumps(old) + "\n")

    reread = list(EvaluationLog(str(path)))
    assert reread[0].validation.stages == stages
    assert reread[1].validation.stages == ()


def test_an_analysis_logs_and_reports_where_the_time_went(repo, tmp_path):
    analysis = analyze(
        repo,
        list(branch_changes(repo, ["feat-b"], base="main")),
        base="main",
        validate=staged_validation(
            [
                ValidationStage("setup", _sleeper(tmp_path, "setup", 0.2)),
                ValidationStage("test", "exit 0"),
            ]
        ),
        log=EvaluationLog(MemoryLines()),
    )
    rows = [e for e in analysis.log if e.validation is not None]
    assert rows and all(
        [s.name for s in e.validation.stages] == ["setup", "test"] for e in rows
    )
    report = markdown_report(analysis)
    assert "setup 0." in report and " · test " in report


#: The validation keys a release before #17 accepts: it builds
#: ``ValidationOutcome(**row["validation"])`` and fails on anything else.
_PRE_17_VALIDATION_KEYS = {
    "ok",
    "failing_tests",
    "failing_files",
    "duration",
    "stdout_tail",
    "returncode",
}


def test_a_new_row_stays_readable_by_a_release_before_stages(tmp_path):
    validate = staged_validation([ValidationStage("test", "exit 0")])
    row = Evaluation(frozenset("a"), Verdict.PASS, validation=validate(str(tmp_path)))
    jdict = json.loads(json.dumps(row.to_jdict()))
    assert set(jdict["validation"]) <= _PRE_17_VALIDATION_KEYS
    assert jdict["validation_stages"][0]["name"] == "test"


def test_a_recorded_outcome_equals_its_reread(tmp_path):
    validate = staged_validation([ValidationStage("test", "exit 0")])
    row = Evaluation(frozenset("a"), Verdict.PASS, validation=validate(str(tmp_path)))
    assert Evaluation.from_jdict(json.loads(json.dumps(row.to_jdict()))) == row


def test_stages_sharing_a_name_are_summed_not_overwritten():
    outcome = ValidationOutcome(
        True, stages=[StageRun("test", 0.3, 0), StageRun("test", 0.4, 0)]
    )
    assert outcome.stage_seconds == {"test": 0.7}


def test_a_stage_with_no_duration_does_not_break_the_report():
    from mergeset.report import stage_breakdown

    row = Evaluation.from_jdict(
        {
            "subset": ["a"],
            "verdict": "pass",
            "validation": {"ok": True},
            "validation_stages": [{"name": "test", "duration": None}],
        }
    )
    assert stage_breakdown(row) == "test 0.0"


def test_show_log_and_the_html_report_carry_the_breakdown(repo, tmp_path):
    from mergeset.cli import show_log
    from mergeset.report import html_report

    log_path = str(tmp_path / "eval.jsonl")
    analysis = analyze(
        repo,
        list(branch_changes(repo, ["feat-b"], base="main")),
        base="main",
        validate=staged_validation([ValidationStage("test", "exit 0")]),
        log_path=log_path,
    )
    assert "test 0." in show_log(log_path=log_path)
    html = html_report(analysis)
    assert '"validation_stages": [{"name": "test"' in html
    assert "${stages(e)}" in html
