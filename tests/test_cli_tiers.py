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
    cli.branches(
        ["feat-a"], repo=repo, base="main", tier=["a:true", "b:true"], retries=2
    )
    assert all(
        "flake_tolerant" in t.validate.__qualname__ for t in seen["tiers"]
    ), [t.validate.__qualname__ for t in seen["tiers"]]


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
        ({"tier": ["a:"]}, "--tier expects 'name:value'"),
        ({"tier": ["a:true"], "tier_cost": ["b:3"]}, "--tier-cost names no tier"),
        ({"tier": ["a:true"], "tier_cost": ["a:0"]}, "seconds > 0"),
        ({"tier": ["a:true"], "tier_cost": ["a:soon"]}, "seconds > 0"),
        ({"tier": ["a:true"], "tier_cost": ["a:1", "a:2"]}, "names `a` twice"),
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
