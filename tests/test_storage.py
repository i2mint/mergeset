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
    made = {}

    def dict_backend(directory):
        return made.setdefault(directory, {})

    store = artifact_store("reports", rootdir=str(tmp_path), store_factory=dict_backend)
    store["k"] = "v"
    assert made == {os.path.join(str(tmp_path), "reports"): {"k": "v"}}
    assert not os.path.exists(os.path.join(str(tmp_path), "reports"))


def test_nothing_is_written_at_the_root(tmp_path):
    """Always a per-kind subfolder, so a fifth kind costs no migration."""
    artifact_store("logs", rootdir=str(tmp_path))["a.log"] = "x"
    assert os.listdir(str(tmp_path)) == ["logs"]


@pytest.mark.parametrize(
    "repo, expected",
    [
        ("/Users/me/proj/i/mergeset", "i-mergeset"),
        ("git@github.com:i2mint/mergeset.git", "i2mint-mergeset"),
        ("https://github.com/i2mint/mergeset", "i2mint-mergeset"),
        (".", "repo"),
    ],
)
def test_slugify_names_a_run_after_its_repo(repo, expected):
    assert slugify(repo) == expected


def test_slugified_names_do_not_escape_the_store(tmp_path):
    """A repo path can be anything; the key it produces must stay a key."""
    for repo in ("../../etc", "/a/b/../c", "weird name/with spaces"):
        key = slugify(repo)
        assert "/" not in key and "\\" not in key and ".." not in key


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
    assert path.endswith("some-private-repo.jsonl")


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
