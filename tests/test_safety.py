"""The refusals: cases where the honest answer is "I could not run this".

Every test here is a case that previously produced a confident, wrong report.
"""

import os
import subprocess

import pytest

from mergeset.analysis import analyze
from mergeset.base import Evaluation, MergesetError, Verdict
from mergeset.log import EvaluationLog, MemoryLines
from mergeset.solve import find_maximal_good_sets
from mergeset.sources import branch_changes
from conftest import py_command, run
from mergeset.validation import (
    ValidationStage,
    callable_validation,
    command_validation,
    detect_runner,
    merge_only_validation,
    staged_validation,
)


def test_a_checkout_error_is_not_a_conflict(repo, tmp_path):
    """A bad reuse_worktree once produced "merge 0 of 15 ... complete"."""
    changes = list(branch_changes(repo, ["feat-a", "feat-b"], base="main"))
    analysis = analyze(
        repo, changes, base="main",
        validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
        reuse_worktree=str(tmp_path / "does-not-exist"),
        check_base=False,
    )
    assert any("could not" in n.lower() or "ABORTED" in n for n in analysis.notes)
    assert analysis.conflicts == [], "an error must never enter the conflict set"


def test_error_evaluations_never_become_conflicts():
    def evaluate(subset):
        if len(subset) > 1:
            return Evaluation(frozenset(subset), Verdict.ERROR, note="disk on fire")
        return Evaluation(frozenset(subset), Verdict.PASS)

    state = find_maximal_good_sets("abc", evaluate)
    assert state.conflicts == []
    assert state.error and "disk on fire" in state.error
    assert not state.exhausted


def test_search_stops_at_the_first_error_rather_than_grinding_on():
    calls = []

    def evaluate(subset):
        calls.append(frozenset(subset))
        return Evaluation(frozenset(subset), Verdict.ERROR, note="nope")

    find_maximal_good_sets("abcdef", evaluate)
    assert len(calls) == 1, "one failed experiment is enough to know we cannot proceed"


def test_a_broken_base_is_a_refusal_not_a_finding(repo):
    changes = list(branch_changes(repo, ["feat-a", "feat-b"], base="main"))
    with pytest.raises(MergesetError) as excinfo:
        analyze(
            repo, changes, base="main",
            validate=command_validation("exit 1"),
            log=EvaluationLog(MemoryLines()),
        )
    message = str(excinfo.value)
    assert "does not pass validation on its own" in message
    assert "check_base=False" in message, "the message must say how to override"


def test_base_check_costs_exactly_one_evaluation(repo):
    changes = list(branch_changes(repo, ["feat-a"], base="main"))
    log = EvaluationLog(MemoryLines())
    analyze(repo, changes, base="main", validate=merge_only_validation(), log=log)
    assert any(e.subset == frozenset() for e in log)


def test_detect_runner_does_not_call_a_js_project_python(tmp_path):
    project = tmp_path / "js"
    project.mkdir()
    (project / "package.json").write_text("{}")
    (project / "tests").mkdir()  # every language has one of these
    assert detect_runner(str(project)) == "npm"


def test_detect_runner_still_finds_python_projects(tmp_path):
    project = tmp_path / "py"
    project.mkdir()
    (project / "pyproject.toml").write_text("")
    assert detect_runner(str(project)) == "pytest"


def test_staged_validation_says_which_stage_failed(tmp_path):
    validate = staged_validation([
        ValidationStage("build", "exit 3"),
        ValidationStage("test", "exit 0"),
    ])
    outcome = validate(str(tmp_path))
    assert not outcome.ok
    assert outcome.failing_tests == ["build: <build failed>"]
    assert "[build]" in outcome.stdout_tail


def test_a_required_stage_failing_stops_the_sequence(tmp_path):
    marker = tmp_path / "ran"
    validate = staged_validation([
        ValidationStage("build", "exit 1"),
        ValidationStage(
            "test",
            py_command(tmp_path, "mark", f"open(r{str(marker)!r}, 'w').close()"),
        ),
    ])
    validate(str(tmp_path))
    assert not marker.exists(), "tests must not run when the build failed"


def test_a_non_required_stage_is_recorded_but_does_not_veto(tmp_path):
    """An advisory lint pass must not exclude every change set."""
    validate = staged_validation([
        ValidationStage("test", "exit 0"),
        ValidationStage("lint", "exit 1", required=False),
    ])
    outcome = validate(str(tmp_path))
    assert outcome.ok, "an advisory stage vetoed the set"
    assert any(f.startswith("lint:") for f in outcome.failing_tests), "not recorded"


def test_a_required_stage_after_an_advisory_one_still_vetoes(tmp_path):
    validate = staged_validation([
        ValidationStage("lint", "exit 1", required=False),
        ValidationStage("test", "exit 1"),
    ])
    outcome = validate(str(tmp_path))
    assert not outcome.ok
    assert [f.split(":")[0] for f in outcome.failing_tests] == ["lint", "test"]


def test_a_fingerprinted_stage_reruns_only_when_its_input_changes(tmp_path):
    from mergeset.validation import file_fingerprint

    worktree = tmp_path / "wt"
    worktree.mkdir()
    lock = worktree / "lock.txt"
    lock.write_text("v1")
    counter = worktree / "count"
    bump = py_command(
        tmp_path, "bump", f"open(r{str(counter)!r}, 'a').write('x\\n')"
    )
    validate = staged_validation([
        ValidationStage("setup", bump, fingerprint=file_fingerprint("lock.txt")),
        ValidationStage("test", "exit 0"),
    ])
    validate(str(worktree))
    validate(str(worktree))
    assert len(counter.read_text().split()) == 1, "setup ran twice for one lockfile"
    lock.write_text("v2")
    validate(str(worktree))
    assert len(counter.read_text().split()) == 2, "setup must rerun when the lock moves"


def test_components_are_not_assumed_to_combine_for_a_whole_repo_validator(repo):
    """A cross-component conflict must still be found.

    feat-b (other.txt) and feat-d (new-d.txt) share no file, so they land in
    different components; a whole-repo validator can still object to the pair,
    exactly as a drift test objects to a change in sources it never names.
    """
    changes = list(branch_changes(repo, ["feat-b", "feat-d"], base="main"))
    analysis = analyze(
        repo, changes, base="main",
        validate=callable_validation(
            lambda worktree: not (
                os.path.exists(os.path.join(worktree, "new-d.txt"))
                and "changed by b"
                in open(os.path.join(worktree, "other.txt")).read()
            )
        ),
        log=EvaluationLog(MemoryLines()),
    )
    assert len(analysis.components) == 2, "the fixture must actually decompose"
    sets = {tuple(sorted(s)) for s in analysis.maximal_sets}
    assert ("feat-b", "feat-d") not in sets, "cross-component conflict was missed"
    assert any("not assumed to combine freely" in n for n in analysis.notes)


def test_a_component_local_validator_is_taken_at_its_word(repo):
    changes = list(branch_changes(repo, ["feat-a", "feat-b", "feat-d"], base="main"))
    analysis = analyze(
        repo, changes, base="main",
        validate=merge_only_validation(),  # declares component_local = True
        log=EvaluationLog(MemoryLines()),
    )
    assert not any("not assumed to combine freely" in n for n in analysis.notes)
    assert {tuple(sorted(s)) for s in analysis.maximal_sets} == {
        ("feat-a", "feat-b", "feat-d")
    }


def test_an_empty_log_is_still_a_log(repo):
    """`log or EvaluationLog(...)` discarded the caller's log while it was empty."""
    log = EvaluationLog(MemoryLines())
    assert bool(log) is True and len(log) == 0
    changes = list(branch_changes(repo, ["feat-a"], base="main"))
    analyze(repo, changes, base="main", validate=merge_only_validation(), log=log)
    assert len(log) > 0, "the caller's log must be the one that gets written"


def test_shrinking_stays_inside_the_stack_closure(repo):
    """Every set the search evaluates must describe what was actually merged.

    Merging a stack tip brings its ancestors whether or not they were named, so
    a non-closed subset is a label for a tree that was never built -- and two
    such labels for the same tree waste an evaluation each.
    """
    from mergeset.base import Evaluation, Verdict
    from mergeset.solve import find_maximal_good_sets
    from mergeset.stacks import ancestors

    forest = {"b": "a", "c": "b", "e": "d"}
    seen = []

    def evaluate(subset):
        seen.append(frozenset(subset))
        bad = {"c", "e"} <= set(subset)
        return Evaluation(frozenset(subset), Verdict.FAIL if bad else Verdict.PASS)

    # As `analyze` wires it: the log is what turns "same tree, two labels" into
    # one cache hit, and it can only do that if the labels are normalized.
    cached = EvaluationLog(MemoryLines()).caching(evaluate)
    find_maximal_good_sets("abcde", cached, depends_on=forest)
    for subset in seen:
        for member in subset:
            assert ancestors(member, forest) <= subset, (
                f"{sorted(subset)} names {member} without its ancestors"
            )
    assert len(seen) == len(set(seen)), "the same tree was evaluated under two labels"


def test_cli_staged_flags_build_the_validator_the_project_needs(tmp_path):
    """The CLI must reach a real project, not only the easy ones."""
    from mergeset.cli import _validator

    lock = tmp_path / "lock.txt"
    lock.write_text("v1")
    counter = tmp_path / "count"
    bump = py_command(tmp_path, "bump2", f"open(r{str(counter)!r}, 'a').write('x\\n')")
    validate = _validator(
        merge_only=False, validate_command=None, timeout=None, retries=0,
        validate_stage=[
            f"setup:{bump}",
            "build:exit 0",
            "test:exit 0",
            "lint:exit 1",
        ],
        validate_fingerprint=["setup:lock.txt"],
        validate_optional=["lint"],
    )
    outcome = validate(str(tmp_path))
    assert outcome.ok, "the optional stage must not veto"
    assert outcome.failing_tests == ["lint: <lint failed>"], "but it is recorded"
    validate(str(tmp_path))
    assert len(counter.read_text().split()) == 1, "fingerprinted setup ran twice"


def test_cli_staged_flags_say_what_is_wrong_with_a_bad_spec():
    from mergeset.cli import _validator

    for kwargs, expected in [
        ({"validate_stage": ["justaname"]}, "--validate-stage expects 'name:value'"),
        (
            {"validate_stage": ["test:pytest"], "validate_fingerprint": ["setup:lock"]},
            "--validate-fingerprint names no stage",
        ),
        (
            {"validate_stage": ["test:pytest"], "validate_optional": ["lint"]},
            "--validate-optional names no stage",
        ),
    ]:
        with pytest.raises(ValueError) as excinfo:
            _validator(
                merge_only=False, validate_command=None, timeout=None, retries=0,
                **{"validate_stage": (), "validate_fingerprint": (),
                   "validate_optional": (), **kwargs},
            )
        assert expected in str(excinfo.value)


def test_a_change_that_never_merged_is_not_reported_as_a_test_failure(repo):
    """It was never validated, so validation has no opinion about it."""
    from mergeset.report import markdown_report

    run(repo, "checkout", "-q", "main")
    with open(os.path.join(repo, "shared.txt"), "w") as f:
        f.write("one\nMAIN MOVED ON\nthree\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-qm", "main edits the same line feat-a edits")

    changes = list(branch_changes(repo, ["feat-a", "feat-b"], base="main"))
    analysis = analyze(
        repo, changes, base="main", validate=merge_only_validation(),
        log=EvaluationLog(MemoryLines()),
    )
    assert "feat-a" in analysis.singleton_conflicts
    report = markdown_report(analysis)
    before, _, after = report.partition("**Conflicts found by validation**")
    assert "feat-a" not in after, "listed again as though a test had failed"
    assert "Will not merge onto the base at all" in before


def test_cache_hits_are_marked_in_the_progress_stream():
    from mergeset.base import Evaluation, Verdict
    from mergeset.solve import find_maximal_good_sets

    events = []

    def evaluate(subset):
        return Evaluation(
            frozenset(subset),
            Verdict.FAIL if {"a", "b"} <= set(subset) else Verdict.PASS,
        )

    # A second search over the same log answers everything from cache; without
    # the marker a caller cannot tell those apart from real, minutes-long runs.
    log = EvaluationLog(MemoryLines())
    cached_evaluate = log.caching(evaluate)
    find_maximal_good_sets("abc", cached_evaluate)
    find_maximal_good_sets(
        "abc", cached_evaluate,
        on_event=lambda name, payload: events.append((name, payload)),
    )
    evaluated = [p for name, p in events if name == "evaluated"]
    assert evaluated, "no evaluation events were emitted"
    assert all(p["cached"] for p in evaluated), "a free re-run looked expensive"
