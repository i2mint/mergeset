"""The CLI's tiered-validation flags: ``--tier``, ``--tier-cost``, ``--confirm-*``
and ``--must-include`` (i2mint/mergeset#20).

The end-to-end tests run real merges in a throwaway repository; the rest stop
at the boundary with :func:`mergeset.analyze_tiered`, where the question is only
what the flags were turned into.
"""

import pytest

import mergeset.cli as cli
from conftest import py_command

_PASS = "raise SystemExit(0)\n"
# Fails on any tree that contains feat-d's file: a conflict only the deep tier sees.
_NO_D = "import os, sys\nsys.exit(1 if os.path.exists('new-d.txt') else 0)\n"


def _captured(monkeypatch):
    """Replace ``analyze_tiered`` with a recorder that stops the run."""
    seen = {}

    def fake(repo, changes, **kwargs):
        seen.update(kwargs)
        raise ValueError("stopped by the test")

    monkeypatch.setattr(cli, "_analyze_tiered", fake)
    return seen


def test_a_deep_tier_refutes_what_the_screen_accepted(repo, tmp_path):
    out = cli.branches(
        ["feat-b", "feat-d"],
        repo=repo,
        base="main",
        tier=[
            f"screen:{py_command(tmp_path, 'pass', _PASS)}",
            f"deep:{py_command(tmp_path, 'nod', _NO_D)}",
        ],
        tier_cost=["deep:30"],
        report_dir=str(tmp_path / "reports"),
        quiet=True,
    )
    assert "Validation was tiered (screen -> deep)" in out
    assert "Tier `screen`:" in out and "Tier `deep`:" in out
    assert "Anytime status:" in out
    report = (tmp_path / "reports" / "REPORT.md").read_text()
    assert "Tier `deep`:" in report  # the price list reaches the written report
    # The screen passes everything; only the deep tier drops feat-d.
    assert "1. `feat-b`" in out and "Dropped: `feat-d`" in out


def test_must_include_reports_the_plan_that_keeps_a_change(repo, tmp_path):
    out = cli.branches(
        ["feat-a", "feat-b", "feat-c"],
        repo=repo,
        base="main",
        merge_only=True,
        tier=["merge"],
        must_include=["feat-c"],
        report_dir=str(tmp_path / "reports"),
        quiet=True,
    )
    assert "Best validated set that keeps feat-c" in out


def test_progress_lines_for_tiers_render(repo, tmp_path, capsys):
    cli.branches(
        ["feat-b"],
        repo=repo,
        base="main",
        tier=[
            f"screen:{py_command(tmp_path, 'pass', _PASS)}",
            f"deep:{py_command(tmp_path, 'pass2', _PASS)}",
        ],
        report_dir=str(tmp_path / "reports"),
    )
    err = capsys.readouterr().err
    assert "tier screen (screen)" in err and "tier deep (confirm)" in err
    assert "anytime:" in err


def test_a_bare_tier_is_the_staged_validator(repo, tmp_path, monkeypatch):
    seen = _captured(monkeypatch)
    cli.branches(
        ["feat-a"],
        repo=repo,
        base="main",
        validate_stage=["test:true"],
        tier=["unit", "e2e:make e2e"],
        tier_cost=["e2e:120", "unit:5"],
        confirm_budget_seconds=600.0,
        confirm_max_runs=3,
        confirm_max_sets=1,
        must_include=["feat-a"],
    )
    unit, e2e = seen["tiers"]
    assert (unit.name, unit.cost, e2e.name, e2e.cost) == ("unit", 5.0, "e2e", 120.0)
    assert unit.validate.__qualname__.startswith("staged_validation")
    assert seen["confirm_budget_seconds"] == 600.0
    assert seen["confirm_max_runs"] == 3 and seen["confirm_max_sets"] == 1
    assert list(seen["must_include"]) == ["feat-a"]
    assert "log_path" not in seen and "validate" not in seen


def test_a_tier_command_may_contain_colons(repo, monkeypatch):
    seen = _captured(monkeypatch)
    cli.branches(["feat-a"], repo=repo, base="main", tier=["e2e:docker run -v a:b x"])
    assert [t.name for t in seen["tiers"]] == ["e2e"]


def test_retries_and_timeout_reach_every_command_tier(repo, monkeypatch):
    seen = _captured(monkeypatch)
    timeouts = []
    real = cli.command_validation

    def recording(command, *, timeout=None, inputs=()):
        timeouts.append((command, timeout))
        return real(command, timeout=timeout, inputs=inputs)

    monkeypatch.setattr(cli, "command_validation", recording)
    cli.branches(
        ["feat-a"],
        repo=repo,
        base="main",
        tier=["a:true", "b:false"],
        retries=2,
        timeout=7.0,
    )
    assert all(
        "flake_tolerant" in t.validate.__qualname__ for t in seen["tiers"]
    ), [t.validate.__qualname__ for t in seen["tiers"]]
    assert timeouts == [("true", 7.0), ("false", 7.0)]


def test_prs_carries_the_whole_tier_surface(repo, monkeypatch):
    from mergeset.base import Change

    seen = _captured(monkeypatch)
    monkeypatch.setattr(cli, "fetch_pull_requests", lambda spec, author=None: [{}])
    monkeypatch.setattr(
        cli,
        "pr_changes",
        lambda repo, prs, base=None: [Change(id="pr7", head="feat-a", base="main")],
    )
    cli.prs(
        "o/r",
        repo=repo,
        tier=["unit:true", "e2e:true"],
        tier_cost=["e2e:9"],
        confirm_budget_seconds=60.0,
        confirm_max_runs=3,
        confirm_max_sets=1,
        must_include=["pr7"],
    )
    assert [(t.name, t.cost) for t in seen["tiers"]] == [("unit", None), ("e2e", 9.0)]
    assert seen["confirm_budget_seconds"] == 60.0
    assert (seen["confirm_max_runs"], seen["confirm_max_sets"]) == (3, 1)
    assert list(seen["must_include"]) == ["pr7"]


def _dispatch(monkeypatch, argv):
    """Run the real command line (cw + argparse), stopping at analyze_tiered."""
    seen = _captured(monkeypatch)
    out = cli.main(argv)
    return seen, out


def test_repeating_a_list_flag_accumulates(repo, monkeypatch):
    seen, _ = _dispatch(
        monkeypatch,
        ["branches", "feat-a", "feat-b", "--repo", repo, "--base", "main",
         "--tier", "unit:true", "--tier", "e2e:true", "deep:true",
         "--tier-cost", "unit:1", "--tier-cost", "e2e:2",
         "--must-include", "feat-a", "--must-include", "feat-b"],
    )  # fmt: skip
    assert [(t.name, t.cost) for t in seen["tiers"]] == [
        ("unit", 1.0),
        ("e2e", 2.0),
        ("deep", None),
    ]
    assert sorted(seen["must_include"]) == ["feat-a", "feat-b"]


def test_a_branch_swallowed_by_tier_is_refused(repo, monkeypatch, capsys):
    seen, out = _dispatch(
        monkeypatch,
        ["branches", "feat-a", "--repo", repo, "--base", "main",
         "--tier", "unit:true", "feat-b"],
    )  # fmt: skip
    text = (out or "") + capsys.readouterr().out
    assert "`feat-b` names a commit in this repository" in text
    assert not seen  # nothing was analysed


def test_a_swallowed_tag_is_refused_too(repo, monkeypatch, capsys):
    from conftest import run

    run(repo, "tag", "v1", "feat-b")
    seen, out = _dispatch(
        monkeypatch,
        ["branches", "feat-a", "--repo", repo, "--base", "main",
         "--tier", "unit:true", "v1"],
    )  # fmt: skip
    assert "`v1` names a commit" in (out or "") + capsys.readouterr().out
    assert not seen


def test_a_tier_named_like_a_branch_can_be_spelt_explicitly(repo, monkeypatch):
    seen, _ = _dispatch(
        monkeypatch,
        ["branches", "feat-a", "--repo", repo, "--base", "main",
         "--validate-command", "true", "--tier", "main:", "deep:true"],
    )  # fmt: skip
    assert [t.name for t in seen["tiers"]] == ["main", "deep"]


def test_numeric_flags_arrive_as_numbers(repo, monkeypatch):
    seen, _ = _dispatch(
        monkeypatch,
        ["branches", "feat-a", "feat-b", "--repo", repo, "--base", "main",
         "--max-seconds", "60", "--max-evaluations", "5", "--timeout", "30",
         "--tier", "unit:true", "deep:true",
         "--confirm-max-runs", "2", "--confirm-budget-seconds", "90"],
    )  # fmt: skip
    assert seen["max_seconds"] == 60.0 and seen["max_evaluations"] == 5
    assert seen["confirm_max_runs"] == 2 and seen["confirm_budget_seconds"] == 90.0
    assert isinstance(seen["confirm_max_runs"], int)


def test_numeric_flags_arrive_as_numbers_without_tiers(repo, monkeypatch):
    got = {}

    def fake_analyze(*args, **kwargs):
        got.update(kwargs)
        raise ValueError("stop here")

    monkeypatch.setattr(cli, "_analyze", fake_analyze)
    cli.main(
        ["branches", "feat-a", "--repo", repo, "-b", "main", "--max-sets", "3",
         "--max-seconds", "1.5"]
    )  # fmt: skip
    assert got["max_sets"] == 3 and got["max_seconds"] == 1.5


def test_a_double_dash_ends_the_tier_list(repo, monkeypatch):
    seen, _ = _dispatch(
        monkeypatch,
        ["branches", "--repo", repo, "--base", "main",
         "--tier", "unit:true", "--", "feat-a", "feat-b"],
    )  # fmt: skip
    assert [t.name for t in seen["tiers"]] == ["unit"]


@pytest.mark.parametrize(
    "kwargs, says",
    [
        ({"tier_cost": ["x:1"]}, "--tier-cost only mean"),
        ({"confirm_budget_seconds": 60.0}, "--confirm-budget-seconds"),
        ({"confirm_max_runs": 2}, "--confirm-max-runs"),
        ({"confirm_max_sets": 1}, "--confirm-max-sets"),
        ({"must_include": ["feat-a"]}, "--must-include"),
        ({"tier": ["a:true"], "log_path": "/x.jsonl"}, "--log-path cannot"),
        ({"tier": ["a:true"], "validate_stage": ["t:true"]}, "no tier runs it"),
        ({"tier": ["a:true"], "validate_command": "true"}, "no tier runs it"),
        ({"tier": ["a:true"], "merge_only": True}, "--merge-only describe"),
        ({"tier": ["a", "b"]}, "Only one --tier can be a bare name"),
        ({"tier": ["pytest -x"]}, "--tier expects 'name:command'"),
        ({"tier": [":true"]}, "--tier expects 'name:value'"),
        ({"tier": ["a:true"], "tier_cost": ["b:3"]}, "--tier-cost names no tier"),
        ({"tier": ["a:true"], "tier_cost": ["a:0"]}, "seconds > 0"),
        ({"tier": ["a:true"], "tier_cost": ["a:soon"]}, "seconds > 0"),
        ({"tier": ["a:true"], "tier_cost": ["a:1", "a:2"]}, "names `a` twice"),
        ({"tier": ["a:true"], "tier_cost": ["a:inf"]}, "finite seconds > 0"),
        ({"tier": []}, "--tier was given no values"),
        ({"confirm_max_runs": 0}, "--confirm-max-runs only mean"),
        ({"confirm_budget_seconds": 0.0}, "--confirm-budget-seconds only mean"),
        ({"tier": ["feat-c"]}, "`feat-c` names a commit"),
        ({"tier": ["a:true"], "confirm_max_runs": -1}, "cannot be negative"),
        ({"tier": ["a:true"], "confirm_budget_seconds": -5.0}, "cannot be negative"),
        ({"tier": ["a:true"], "must_include": ["nope"]}, "--must-include names"),
        ({"tier": ["a:true"], "must_include": []}, "--must-include was given no"),
        ({"tier": ["a:true"], "tier_cost": []}, "--tier-cost was given no"),
        ({"report_format": ["markdown", "feat-b"]}, "--report-format names no"),
    ],
)
def test_options_that_cannot_mean_anything_are_refused(repo, monkeypatch, kwargs, says):
    def must_not_run(*args, **kw):
        raise AssertionError("an analysis started despite a bad option")

    monkeypatch.setattr(cli, "_analyze_tiered", must_not_run)
    monkeypatch.setattr(cli, "_analyze", must_not_run)
    out = cli.branches(["feat-a"], repo=repo, base="main", **kwargs)
    assert out.startswith("mergeset could not read that option"), out
    assert says in out, out


def test_an_unknown_must_include_costs_nothing(repo, tmp_path):
    marker = tmp_path / "ran"
    touch = py_command(tmp_path, "touch", f"open({str(marker)!r}, 'w').close()\n")
    out = cli.branches(
        ["feat-a", "feat-b"],
        repo=repo,
        base="main",
        tier=[f"unit:{touch}"],
        must_include=["feat-typo"],
        quiet=True,
    )
    assert "not candidates: feat-typo" in out
    assert not marker.exists()


def test_without_tier_the_untiered_path_is_unchanged(repo, monkeypatch):
    seen = {}

    def fake_analyze(*args, **kwargs):
        seen.update(kwargs)
        raise ValueError("stop here")

    def must_not_run(*args, **kw):
        raise AssertionError("tiered path taken without --tier")

    monkeypatch.setattr(cli, "_analyze", fake_analyze)
    monkeypatch.setattr(cli, "_analyze_tiered", must_not_run)
    cli.branches(["feat-a"], repo=repo, base="main", log_path="/x.jsonl")
    assert seen["log_path"] == "/x.jsonl" and callable(seen["validate"])


def _tiered(repo, tiers, **kwargs):
    from mergeset import analyze_tiered, branch_changes

    changes = list(branch_changes(repo, ["feat-b", "feat-d"], base="main"))
    return analyze_tiered(repo, changes, tiers=tiers, base="main", **kwargs)


def test_cost_lines_say_where_each_price_came_from(repo, tmp_path):
    from mergeset import Tier
    from mergeset.validation import command_validation

    ok = command_validation(py_command(tmp_path, "pass", _PASS))
    result = _tiered(
        repo,
        [Tier("screen", ok), Tier("deep", ok, cost=40.0), Tier("deeper", ok)],
        confirm_max_runs=0,
    )
    screen, deep, deeper = result.cost_lines()
    assert screen.startswith("Tier `screen`: ") and " runs on record, " in screen
    assert "priced from measurements, median" in screen
    assert "priced as declared, 40.0s per run" in deep
    assert deep.endswith("; skipped (the reason is in the notes).")
    assert "0 runs on record, 0.0s in total" in deep
    # The run stopped at `deep`, so `deeper` was never priced by anyone.
    assert "no measured or declared price, so a default of" in deeper


def test_every_tier_merges_the_way_the_screen_does(repo, tmp_path, monkeypatch):
    import mergeset.tiers as tiers
    from mergeset import Tier
    from mergeset.validation import command_validation

    calls = []
    real = tiers.git_oracle

    def recording(*args, **kwargs):
        calls.append(kwargs.get("reuse_worktree"))
        return real(*args, **kwargs)

    monkeypatch.setattr(tiers, "git_oracle", recording)
    ok = command_validation(py_command(tmp_path, "pass", _PASS))
    wt = str(tmp_path / "wt")
    from mergeset.gitops import persistent_worktree

    persistent_worktree(repo, "main", wt)
    _tiered(repo, [Tier("screen", ok), Tier("deep", ok)], reuse_worktree=wt)
    assert calls and all(c == wt for c in calls), calls


def test_branches_takes_several_positional_branches(repo, monkeypatch):
    seen = {}

    def fake_analyze(repo, changes, **kwargs):
        seen["ids"] = [c.id for c in changes]
        raise ValueError("stop here")

    monkeypatch.setattr(cli, "_analyze", fake_analyze)
    cli.main(["branches", "feat-a", "feat-b", "--repo", repo, "-b", "main"])
    assert seen["ids"] == ["feat-a", "feat-b"]


def test_a_cost_model_without_a_summary_is_not_called_a_default(repo, tmp_path):
    from mergeset import Tier
    from mergeset.validation import command_validation

    class Flat:
        def estimate(self, tier, subset):
            return 3.0

        pessimistic = estimate

        def observe(self, tier, subset, seconds):
            pass

        def is_measured(self, tier):
            return False

    ok = command_validation(py_command(tmp_path, "pass", _PASS))
    result = _tiered(repo, [Tier("screen", ok)], cost_model=Flat())
    (line,) = result.cost_lines()
    assert "priced by the cost model at 3.0s per run" in line
