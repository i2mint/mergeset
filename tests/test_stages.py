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
    del old["validation"]["stages"]  # a row written before #17
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
