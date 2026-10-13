"""A validator's fingerprint covers the scripts it runs, when it is told them (#39).

Since #32 a row is pinned to the validator's fingerprint, a digest of its
command *text*. A command such as ``python /elsewhere/check.py`` keeps its
fingerprint when ``check.py`` is edited, so the old script's verdicts answered
the new one. Files inside the analysed repository are pinned by the commits; a
script outside it is pinned only when named with ``inputs=`` (library) or
``--validate-input`` (CLI). These tests edit the script, not the command.
"""

import pytest

from mergeset.analysis import analyze
from mergeset.base import CapabilityError
from mergeset.log import EvaluationLog
from mergeset.sources import branch_changes
from mergeset.validation import (
    ValidationStage,
    act_validation,
    command_validation,
    fingerprint_of,
    flake_tolerant,
    inputs_digest,
    js_validation,
    pytest_validation,
    staged_validation,
)
import mergeset.cli as cli
from conftest import py_command

_PASS = "raise SystemExit(0)\n"
# Fails on any tree that contains feat-d's file.
_NO_D = "import os, sys\nsys.exit(1 if os.path.exists('new-d.txt') else 0)\n"


def _analyze(repo, log, validate):
    changes = list(branch_changes(repo, ["feat-b", "feat-d"], base="main"))
    return analyze(
        repo,
        changes,
        base="main",
        validate=validate,
        pairwise_preoracle=False,
        decompose=False,
        log=log,
    )


def _sets(analysis):
    return {tuple(sorted(s)) for s in analysis.maximal_sets}


def test_an_edited_input_script_asks_a_new_question(repo, tmp_path):
    """The issue's repro: same command, edited script."""
    path = str(tmp_path / "eval.jsonl")
    command = py_command(tmp_path, "check", _PASS)
    script = str(tmp_path / "check.py")

    first = _analyze(repo, EvaluationLog(path), command_validation(command, inputs=[script]))
    assert _sets(first) == {("feat-b", "feat-d")}

    (tmp_path / "check.py").write_text(_NO_D)
    second = _analyze(
        repo, EvaluationLog(path), command_validation(command, inputs=[script])
    )
    assert _sets(second) == {("feat-b",)}, "the old script's passes answered"
    assert second.evaluations_this_run > 0
    assert second.log.other_validator


def test_an_unchanged_input_still_makes_a_rerun_free(repo, tmp_path):
    path = str(tmp_path / "eval.jsonl")
    command = py_command(tmp_path, "check", _PASS)
    script = str(tmp_path / "check.py")
    _analyze(repo, EvaluationLog(path), command_validation(command, inputs=[script]))
    again = _analyze(
        repo, EvaluationLog(path), command_validation(command, inputs=[script])
    )
    assert again.evaluations_this_run == 0


def test_no_inputs_keeps_the_fingerprint_rows_already_carry():
    """Naming no input must not retire every existing log's rows on upgrade."""
    assert fingerprint_of(command_validation("make test")) == fingerprint_of(
        command_validation("make test", inputs=[])
    )
    assert fingerprint_of(pytest_validation()) == fingerprint_of(
        pytest_validation(inputs=())
    )


def test_every_shipped_runner_folds_its_inputs_in(tmp_path):
    script = tmp_path / "x.sh"
    script.write_text("v1")
    makers = {
        "command": lambda **kw: command_validation("sh x.sh", **kw),
        "pytest": lambda **kw: pytest_validation(**kw),
        "act": lambda **kw: act_validation(**kw),
        "staged": lambda **kw: staged_validation(
            [ValidationStage("t", "sh x.sh")], **kw
        ),
        "retried": lambda **kw: flake_tolerant(
            command_validation("sh x.sh", **kw), retries=2
        ),
    }
    before = {k: fingerprint_of(m(inputs=[str(script)])) for k, m in makers.items()}
    script.write_text("v2")
    for kind, make in makers.items():
        assert fingerprint_of(make(inputs=[str(script)])) != before[kind], kind


def test_inputs_digest_spellings_and_shapes(tmp_path, monkeypatch):
    folder = tmp_path / "checks"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "a.py").write_text("a")
    monkeypatch.chdir(tmp_path)
    # Relative to the current directory, not the worktree; one key per file.
    assert inputs_digest(["checks", str(folder)]) == inputs_digest([str(folder)])
    before = inputs_digest([str(folder)])
    (folder / "sub" / "a.py").write_text("b")
    assert inputs_digest([str(folder)]) != before, "a file under a directory"
    edited = inputs_digest([str(folder)])
    (folder / "sub" / "a.py").rename(folder / "sub" / "b.py")
    assert inputs_digest([str(folder)]) != edited, "a renamed file"
    assert inputs_digest([str(tmp_path / "nope")]) == {
        str(tmp_path / "nope"): "missing"
    }


def test_validate_input_retires_an_edited_tier_script(repo, tmp_path):
    def run():
        return cli.branches(
            ["feat-b", "feat-d"],
            repo=repo,
            base="main",
            tier=[f"u:{py_command_existing(tmp_path)}"],
            validate_input=[str(tmp_path / "check.py")],
            report_dir=str(tmp_path / "reports"),
            quiet=True,
        )

    (tmp_path / "check.py").write_text(_PASS)
    assert "Dropped: `feat-d`" not in run()
    (tmp_path / "check.py").write_text(_NO_D)
    second = run()
    assert "Dropped: `feat-d`" in second, "the old script's passes answered"
    assert "judged by a different validator" in second


def test_validate_input_reaches_the_untiered_validator(repo, tmp_path):
    def run():
        return cli.branches(
            ["feat-b", "feat-d"],
            repo=repo,
            base="main",
            validate_command=py_command_existing(tmp_path),
            validate_input=[str(tmp_path / "check.py")],
            log_path=str(tmp_path / "eval.jsonl"),
            report_dir=str(tmp_path / "reports"),
            quiet=True,
        )

    (tmp_path / "check.py").write_text(_PASS)
    assert "Dropped: `feat-d`" not in run()
    (tmp_path / "check.py").write_text(_NO_D)
    assert "Dropped: `feat-d`" in run()


def test_validate_input_with_merge_only_is_refused(repo, tmp_path):
    out = cli.branches(
        ["feat-b"],
        repo=repo,
        base="main",
        merge_only=True,
        validate_input=[str(_touch(tmp_path / "x.py"))],
        report_dir=str(tmp_path / "reports"),
        quiet=True,
    )
    assert "--validate-input" in out and "--merge-only" in out


def py_command_existing(tmp_path):
    """The command for ``tmp_path/check.py``, without (re)writing the script."""
    import sys

    return f'"{sys.executable}" "{tmp_path / "check.py"}"'



def _touch(path):
    path.write_text("")
    return path


def test_a_branch_typed_after_validate_input_is_refused(repo, tmp_path):
    out = cli.branches(
        ["feat-b"],
        repo=repo,
        base="main",
        validate_command="true",
        validate_input=[str(_touch(tmp_path / "chk.sh")), "feat-d"],
        report_dir=str(tmp_path / "reports"),
        quiet=True,
    )
    assert "--validate-input names no file: feat-d" in out


def test_an_input_edited_mid_run_stops_the_run(tmp_path):
    script = tmp_path / "check.py"
    script.write_text(_PASS)
    validate = command_validation(py_command_existing(tmp_path), inputs=[str(script)])
    assert validate(str(tmp_path)).ok
    script.write_text(_NO_D)
    with pytest.raises(CapabilityError, match="changed since the validator was made"):
        validate(str(tmp_path))


def test_an_input_edited_while_it_runs_is_not_recorded(tmp_path):
    script = tmp_path / "check.py"
    # The script rewrites itself, as an edit landing mid-evaluation would.
    script.write_text(
        "import sys\nopen(sys.argv[0], 'a').write('# edited')\n"
    )
    validate = command_validation(py_command_existing(tmp_path), inputs=[str(script)])
    with pytest.raises(CapabilityError, match="while it ran"):
        validate(str(tmp_path))


def test_a_lone_string_is_not_read_as_characters(tmp_path):
    with pytest.raises(TypeError, match="wrap it in a list"):
        command_validation("true", inputs=str(tmp_path / "check.py"))
    with pytest.raises(TypeError):
        inputs_digest(str(tmp_path))


def test_a_symlinked_subdirectory_is_followed(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "h.py").write_text("1")
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "lib").symlink_to(lib)
    (checks / "loop").symlink_to(checks)  # a cycle must terminate
    before = inputs_digest([str(checks)])
    (lib / "h.py").write_text("2")
    assert inputs_digest([str(checks)]) != before


def test_a_symlink_and_its_target_are_one_input(tmp_path):
    (tmp_path / "check.py").write_text("x")
    (tmp_path / "alias.py").symlink_to(tmp_path / "check.py")
    assert fingerprint_of(
        command_validation("c", inputs=[str(tmp_path / "alias.py")])
    ) == fingerprint_of(command_validation("c", inputs=[str(tmp_path / "check.py")]))


def test_js_validation_takes_inputs(tmp_path):
    script = tmp_path / "x.js"
    script.write_text("1")
    before = fingerprint_of(js_validation(inputs=[str(script)]))
    script.write_text("2")
    assert fingerprint_of(js_validation(inputs=[str(script)])) != before
    assert fingerprint_of(js_validation()) == fingerprint_of(js_validation(inputs=[]))


def test_inputs_with_an_unfingerprinted_pytest_selection_are_refused(tmp_path):
    with pytest.raises(ValueError, match="select_paths"):
        pytest_validation(select_paths=lambda wt: [], inputs=[str(tmp_path)])
