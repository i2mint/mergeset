"""A run that aborted says so: header, banner, log rows, exit status (#53).

When a search met an ERROR (a resolver that timed out, ADR 0036) the report said
"partial (budget reached)", the CLI exited 0 and the log table showed
"conflict: <files>" for a row that decided nothing.
"""

import io

import pytest

import mergeset.cli as cli
from mergeset.analysis import analyze
from mergeset.base import Change, Verdict
from mergeset.report import html_report, markdown_report
from mergeset.validation import command_validation
from conftest import py_command

_PASS = "raise SystemExit(0)\n"


def _raising(worktree, files):
    raise TimeoutError("resolver timed out")


@pytest.fixture
def aborted(repo, tmp_path):
    return analyze(
        repo,
        [Change(id=n, head=n, base="main") for n in ("feat-a", "feat-c")],
        base="main",
        validate=command_validation(py_command(tmp_path, "pass", _PASS)),
        resolver=_raising,
        pairwise_preoracle=False,
        decompose=False,
        use_ci_status=False,
    )


def test_the_analysis_knows_it_aborted(aborted):
    assert "TimeoutError" in aborted.aborted


def test_the_header_and_banner_say_aborted_not_budget(aborted):
    text = markdown_report(aborted)
    header = text.splitlines()[2]
    assert "ABORTED" in header and "budget" not in header
    assert "> **Aborted:**" in text and "TimeoutError" in text
    assert "this is not a finding" in text


def test_a_clean_run_is_not_called_aborted(repo, tmp_path):
    clean = analyze(
        repo,
        [Change(id=n, head=n, base="main") for n in ("feat-b", "feat-d")],
        base="main",
        validate=command_validation(py_command(tmp_path, "pass", _PASS)),
        pairwise_preoracle=False,
        decompose=False,
        use_ci_status=False,
    )
    assert clean.aborted is None
    assert "ABORTED" not in markdown_report(clean)


def test_the_log_table_shows_the_error_not_a_conflict(aborted):
    from mergeset.report import _log_table

    table = "\n".join(_log_table(aborted.log))
    (row,) = [line for line in table.splitlines() if "| error |" in line]
    assert "TimeoutError" in row and "conflict:" not in row
    assert "asked again" in table


def test_the_html_data_carries_the_abort(aborted):
    page = html_report(aborted)
    assert '"aborted": "' in page and "TimeoutError" in page


def test_the_cli_exits_3_on_an_abort_and_0_otherwise(repo, tmp_path, monkeypatch):
    real = cli._analyze
    resolver = {"fn": _raising}

    def patched(repo_, changes, **kwargs):
        kwargs["resolver"] = resolver["fn"]
        return real(repo_, changes, **kwargs)

    monkeypatch.setattr(cli, "_analyze", patched)
    argv = [
        "branches",
        "feat-a",
        "feat-c",
        "--repo",
        repo,
        "--base",
        "main",
        "--validate-command",
        py_command(tmp_path, "pass", _PASS),
        "--no-pairwise",
        "--no-decompose",
        "--report-dir",
        str(tmp_path / "reports"),
    ]
    out = io.StringIO()
    import contextlib

    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    assert code == cli.EXIT_ABORTED == 3
    assert "ABORTED" in out.getvalue()

    # A run that does not abort exits 0.
    resolver["fn"] = None
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    assert code == 0 and "ABORTED" not in out.getvalue()


def test_a_deep_tier_abort_does_not_disown_the_screens_answer(
    repo, tmp_path, monkeypatch
):
    """Review of #57: the banner called a finished screen's plans 'not an answer'."""
    import mergeset.tiers as tiers_module
    from mergeset.solve import SearchState
    from mergeset.tiers import Tier, analyze_tiered

    def deep_search_aborts(*args, **kwargs):
        # `tiers` runs a search only for the confirm tiers; the screen's is
        # `analyze`'s own.
        state = SearchState()
        state.maximal_good_sets = [frozenset({"feat-b"})]  # partial, unconfirmed
        state.error = "the deep tier's resolution is gone"
        return state

    monkeypatch.setattr(tiers_module, "find_maximal_good_sets", deep_search_aborts)
    ok = command_validation(py_command(tmp_path, "pass", _PASS))
    deep = command_validation(py_command(tmp_path, "deep", _PASS))
    result = analyze_tiered(
        repo,
        [Change(id=n, head=n, base="main") for n in ("feat-b", "feat-d")],
        base="main",
        tiers=[Tier("screen", ok), Tier("deep", deep)],
        pairwise_preoracle=False,
        decompose=False,
        use_ci_status=False,
    )
    analysis = result.analysis
    assert analysis.aborted_tier == "deep"
    text = markdown_report(analysis)
    assert "ABORTED at tier `deep`" in text.splitlines()[2]
    assert "hold at the depth they reached" in text
    assert "not an answer" not in text and "this is not a finding" not in text
    assert "No conflicts found by the tiers that finished" in text
    assert any("ran but it aborted" in n for n in analysis.notes)
    # The aborted tier is not "reached", and its partial sets are not the answer.
    assert result.depth_reached == "screen"
    assert analysis.maximal_sets == [frozenset({"feat-b", "feat-d"})]
    assert any("only reached `screen`" in n for n in analysis.notes)
    assert not any("confirmed at the deepest tier" in n for n in analysis.notes)
