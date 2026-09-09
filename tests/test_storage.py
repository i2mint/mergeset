"""The artifact storage seam: default location, kinds, and backend swap.

The point of these tests is not that a Mapping works. It is that mergeset
*cannot* be made to write derived data into the repository it analysed, because
that is how a private repo's internals ended up committed to a public one.
"""

import os
import subprocess
import sys

import pytest

from mergeset.storage import (
    ARTIFACT_KINDS,
    app_data_rootdir,
    artifact_mall,
    artifact_path,
    artifact_store,
    evaluation_log_path,
    slugify,
)


def test_rootdir_is_outside_any_repo_and_env_overridable(tmp_path, monkeypatch):
    monkeypatch.delenv("MERGESET_DATA_DIR", raising=False)
    default = app_data_rootdir()
    assert default.endswith(os.path.join("", "mergeset")) or default.endswith(
        "mergeset"
    )
    assert os.path.isabs(default)

    monkeypatch.setenv("MERGESET_DATA_DIR", str(tmp_path))
    assert app_data_rootdir() == str(tmp_path)


def test_one_knob_for_the_root_not_one_per_kind(tmp_path, monkeypatch):
    """A single env var moves every kind; there is no per-kind override."""
    monkeypatch.setenv("MERGESET_DATA_DIR", str(tmp_path))
    for kind in ARTIFACT_KINDS:
        assert artifact_path(kind).startswith(str(tmp_path))


def test_mall_exposes_exactly_the_kinds(tmp_path):
    mall = artifact_mall(rootdir=str(tmp_path))
    assert sorted(mall) == sorted(ARTIFACT_KINDS)
    with pytest.raises(KeyError):
        mall["nonsense"]


def test_stores_are_mutable_mappings_with_nested_keys(tmp_path):
    reports = artifact_store("reports", rootdir=str(tmp_path))
    reports["run-a/REPORT.md"] = "# a"
    reports["run-a/report.html"] = "<h1>a</h1>"
    assert reports["run-a/REPORT.md"] == "# a"
    assert sorted(reports) == ["run-a/REPORT.md", "run-a/report.html"]
    del reports["run-a/report.html"]
    assert sorted(reports) == ["run-a/REPORT.md"]


def test_kinds_do_not_share_a_namespace(tmp_path):
    mall = artifact_mall(rootdir=str(tmp_path))
    mall["reports"]["x"] = "report"
    mall["logs"]["x"] = "log"
    assert mall["reports"]["x"] == "report"
    assert mall["logs"]["x"] == "log"


def test_backend_is_a_keyword_argument(tmp_path):
    """The S3 migration is this: pass a different factory. Nothing else moves."""
    seen = []

    def dict_backend(kind, rootdir):
        seen.append((kind, rootdir))
        return {}

    store = artifact_store("reports", rootdir=str(tmp_path), store_factory=dict_backend)
    store["k"] = "v"
    assert store == {"k": "v"}
    # The factory is handed the KIND and the ROOT separately, never a joined
    # filesystem path: a backend with no filesystem must not have to parse one
    # out, and on Windows a joined path would put backslashes in S3 keys.
    assert seen == [("reports", str(tmp_path))]
    assert not os.path.exists(os.path.join(str(tmp_path), "reports"))


def test_a_non_filesystem_backend_needs_no_filesystem(tmp_path):
    """The whole point: nothing is created on disk when the backend is not disk."""
    backing = {}
    mall = artifact_mall(
        rootdir=str(tmp_path / "never-created"),
        store_factory=lambda kind, root: backing.setdefault(kind, {}),
    )
    mall["reports"]["a/b.md"] = "x"
    mall["evaluations"]["c.jsonl"] = "{}"
    assert backing == {"reports": {"a/b.md": "x"}, "evaluations": {"c.jsonl": "{}"}}
    assert not os.path.exists(str(tmp_path / "never-created"))


def test_nothing_is_written_at_the_root(tmp_path):
    """Always a per-kind subfolder, so a fifth kind costs no migration."""
    artifact_store("logs", rootdir=str(tmp_path))["a.log"] = "x"
    assert os.listdir(str(tmp_path)) == ["logs"]


@pytest.mark.parametrize(
    "repo, readable",
    [
        ("/Users/me/proj/i/mergeset", "i-mergeset"),
        ("git@github.com:i2mint/mergeset.git", "i2mint-mergeset"),
        ("https://github.com/i2mint/mergeset", "i2mint-mergeset"),
        (".", "repo"),
    ],
)
def test_slugify_names_a_run_after_its_repo(repo, readable):
    """The key is readable, and carries a digest so it is also unique."""
    key = slugify(repo)
    assert key.startswith(readable + "-")
    assert len(key) == len(readable) + 7  # '-' + 6 hex


@pytest.mark.parametrize(
    "a, b",
    [
        ("/a/b/proj", "/c/b/proj"),  # same last two components
        ("/x/" + "a" * 80 + "/one", "/x/" + "a" * 80 + "/two"),  # past maxlen
        ("/p/q", "/p/q/"),  # only if they really differ after normalisation
    ],
)
def test_different_repos_never_share_a_key(a, b):
    """Two repos sharing one evaluation log would mix their change ids into one
    monotone closure — a wrong answer, not an untidy one."""
    if a.rstrip("/") == b.rstrip("/"):
        pytest.skip("same repo")
    assert slugify(a) != slugify(b)


def test_a_long_parent_does_not_swallow_the_repo_name():
    key = slugify("/x/" + "a" * 80 + "/mergeset")
    assert "mergeset" in key, key


def test_slugified_names_stay_inside_the_store(tmp_path):
    """A repo path can be anything; the key it produces must stay one key."""
    root = str(tmp_path)
    adversarial = [
        "../../etc",
        "/a/b/../c",
        "weird name/with spaces",
        "..",
        "/",
        "",
        "   ",
        ".git",
        "---",
        "C:\\Users\\me\\proj",
        "/a/b/" + "x" * 300,
        "a\tb",
        "naïve/répo",
    ]
    for repo in adversarial:
        key = slugify(repo)
        assert key, f"{repo!r} produced an empty key"
        assert "/" not in key and "\\" not in key, key
        resolved = os.path.normpath(os.path.join(root, key))
        assert os.path.dirname(resolved) == os.path.normpath(root), (
            f"{repo!r} -> {key!r} escapes the store"
        )


# -- the regression this whole module exists for ---------------------------


def test_evaluation_log_never_defaults_inside_the_analysed_repo(tmp_path):
    """The default log path must not be under the repository being analysed.

    It used to be ``<repo>/.mergeset/evaluations.jsonl`` — a file recording one
    repository's internals, written into that repository, one ``git add .`` away
    from being published.
    """
    repo = tmp_path / "some-private-repo"
    repo.mkdir()
    store_root = tmp_path / "artifacts"
    path = evaluation_log_path(str(repo), rootdir=str(store_root))
    assert not os.path.abspath(path).startswith(os.path.abspath(str(repo)) + os.sep)
    assert os.path.abspath(path).startswith(os.path.abspath(str(store_root)))
    assert "some-private-repo-" in os.path.basename(path)
    assert path.endswith(".jsonl")


def test_analyze_defaults_its_log_to_the_artifact_store(tmp_path, monkeypatch):
    """End to end through the real call path, not through the helper."""
    monkeypatch.setenv("MERGESET_DATA_DIR", str(tmp_path / "artifacts"))
    repo = _one_commit_repo(tmp_path / "repo")

    from mergeset.analysis import analyze
    from mergeset.validation import merge_only_validation
    from mergeset.sources import branch_changes

    changes = list(branch_changes(repo, ["feature"], base="main"))
    analyze(repo, changes, base="main", validate=merge_only_validation())

    assert not os.path.exists(os.path.join(repo, ".mergeset"))
    written = [
        os.path.join(dirpath, f)
        for dirpath, _, files in os.walk(str(tmp_path / "artifacts"))
        for f in files
    ]
    assert any(
        p.endswith(".jsonl") and os.sep + "evaluations" + os.sep in p for p in written
    ), written


def _one_commit_repo(path) -> str:
    """A minimal repo with `main` and a `feature` branch, for the end-to-end test."""
    path = str(path)
    os.makedirs(path, exist_ok=True)
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=path, check=True, capture_output=True
    )
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    with open(os.path.join(path, "a.txt"), "w") as f:
        f.write("base\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    run("checkout", "-q", "-b", "feature")
    with open(os.path.join(path, "b.txt"), "w") as f:
        f.write("feature\n")
    run("add", "-A")
    run("commit", "-qm", "feature")
    run("checkout", "-q", "main")
    return path


# -- the key namespace must not change shape with the operating system -----


def test_keys_are_slash_separated_on_every_platform():
    """A backslash platform must not rename every nested key.

    Windows CI caught this: ``dol`` handed back ``'run-a\\REPORT.md'`` for a key
    written as ``'run-a/REPORT.md'``, so the same key was two different keys on
    two machines — and an S3 backend uses ``/`` regardless.
    """
    from mergeset.storage import slash_separated_keys

    backing = {}
    store = slash_separated_keys(backing, sep="\\")
    store["run-a/REPORT.md"] = "# a"
    assert list(backing) == ["run-a\\REPORT.md"], "the backend keeps native keys"
    assert list(store) == ["run-a/REPORT.md"], "callers always see slashes"
    assert store["run-a/REPORT.md"] == "# a"
    del store["run-a/REPORT.md"]
    assert backing == {}


def test_slash_platform_is_left_alone():
    backing = {}
    assert slash_separated_keys_is_identity(backing)


def slash_separated_keys_is_identity(store):
    from mergeset.storage import slash_separated_keys

    return slash_separated_keys(store, sep="/") is store


def test_real_store_round_trips_a_nested_key_under_the_native_separator(tmp_path):
    """Whatever ``os.sep`` is, the key the caller used is the key they get back."""
    store = artifact_store("reports", rootdir=str(tmp_path))
    store["a/b/c.md"] = "x"
    assert list(store) == ["a/b/c.md"]
    assert store["a/b/c.md"] == "x"
    assert os.path.isfile(os.path.join(str(tmp_path), "reports", "a", "b", "c.md"))


# -- the seam has to reach production, not just exist ----------------------


def test_analyze_writes_its_log_through_a_caller_supplied_store(tmp_path):
    """`artifacts=` is the S3 migration. It must reach the log with no other change."""
    backing = {}
    mall = artifact_mall(
        rootdir=str(tmp_path / "unused"),
        store_factory=lambda kind, root: backing.setdefault(kind, {}),
    )
    repo = _one_commit_repo(tmp_path / "repo")

    from mergeset.analysis import analyze
    from mergeset.sources import branch_changes
    from mergeset.validation import merge_only_validation

    changes = list(branch_changes(repo, ["feature"], base="main"))
    analyze(
        repo, changes, base="main", validate=merge_only_validation(), artifacts=mall
    )

    assert list(backing) == ["evaluations"], backing
    (key,) = backing["evaluations"]
    assert key.endswith(".jsonl")
    assert backing["evaluations"][key].strip(), "the log must actually be written"
    assert not os.path.exists(str(tmp_path / "unused")), (
        "a non-filesystem backend must not create directories"
    )


def test_a_bare_evaluation_log_does_not_write_to_the_working_directory(
    tmp_path, monkeypatch
):
    """`EvaluationLog()` used to default to ./evaluations.jsonl."""
    from mergeset.log import EvaluationLog

    monkeypatch.setenv("MERGESET_DATA_DIR", str(tmp_path / "artifacts"))
    monkeypatch.chdir(tmp_path)
    log = EvaluationLog()
    from mergeset.base import Evaluation, Verdict

    log.record(Evaluation(frozenset({"a"}), Verdict.PASS))
    assert not os.path.exists(str(tmp_path / "evaluations.jsonl"))
    assert os.path.isdir(str(tmp_path / "artifacts" / "evaluations"))


def test_store_lines_round_trip_through_a_plain_dict():
    from mergeset.log import EvaluationLog, StoreLines
    from mergeset.base import Evaluation, Verdict

    backing = {}
    log = EvaluationLog(StoreLines(backing, "run.jsonl"))
    log.record(Evaluation(frozenset({"a", "b"}), Verdict.PASS))
    log.record(Evaluation(frozenset({"c"}), Verdict.FAIL))
    reread = EvaluationLog(StoreLines(backing, "run.jsonl"))
    assert len(reread) == 2
    assert reread.known(frozenset({"a"})).verdict is Verdict.PASS


# -- reports: one run must not overwrite another ---------------------------


def test_a_rerun_does_not_overwrite_the_previous_report(tmp_path):
    """The interesting thing about a re-run is the diff against the run before."""
    from mergeset.cli import _emit_reports
    from mergeset.storage import run_key

    analysis = _stub_analysis(repo="/some/where/proj")
    reports = {}
    first = _emit_reports(
        analysis, None, "t", reports=reports, run=run_key(analysis.repo, at="run-1")
    )
    second = _emit_reports(
        analysis, None, "t", reports=reports, run=run_key(analysis.repo, at="run-2")
    )
    assert len(reports) == 4, sorted(reports)
    assert set(first).isdisjoint(second)


def test_two_repos_do_not_share_a_report_key(tmp_path):
    """`--repo .` slugified to the literal 'repo' for every project."""
    from mergeset.cli import _emit_reports

    a, b = _stub_analysis(repo="."), _stub_analysis(repo=str(tmp_path))
    reports = {}
    _emit_reports(a, None, "t", reports=reports)
    _emit_reports(b, None, "t", reports=reports)
    assert len(reports) == 4, sorted(reports)


def test_an_explicit_report_dir_is_still_honoured(tmp_path):
    from mergeset.cli import _emit_reports

    out = str(tmp_path / "here")
    written = _emit_reports(_stub_analysis(), out, "t")
    assert sorted(os.listdir(out)) == ["REPORT.md", "report.html"]
    assert all(w.startswith(out) for w in written)


def _stub_analysis(repo="/x/y/proj"):
    """The smallest Analysis the report renderers accept."""
    from mergeset.analysis import Analysis

    return Analysis(repo=repo, base="main", base_sha="0" * 40, changes=[])
