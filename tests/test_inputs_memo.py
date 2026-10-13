"""Inputs are digested once per run, not once per validator built (#42).

A run digested ``--validate-input`` once per tier, once for a default
validator no tier ran, and twice around every evaluation; a large directory
input (a venv) made that minutes. File digests are now memoised by stat, and
the bare validator is built only when a bare tier runs it.
"""

import os

import mergeset.cli as cli
import mergeset.validation as validation
from mergeset.validation import inputs_digest

from test_cli_tiers import _captured


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def test_only_command_tiers_build_no_bare_validator(repo, monkeypatch):
    seen = _captured(monkeypatch)
    built = []
    monkeypatch.setattr(cli, "_validator", lambda **kw: built.append(kw))
    cli.branches(["feat-a"], repo=repo, base="main", tier=["a:true", "b:false"])
    assert [t.name for t in seen["tiers"]] == ["a", "b"]
    assert built == []


def test_a_bare_tier_still_builds_it_once(repo, monkeypatch):
    seen = _captured(monkeypatch)
    built = []
    real = cli._validator
    monkeypatch.setattr(
        cli, "_validator", lambda **kw: built.append(kw) or real(**kw)
    )
    cli.branches(["feat-a"], repo=repo, base="main", tier=["unit", "b:false"])
    assert [t.name for t in seen["tiers"]] == ["unit", "b"]
    assert len(built) == 1


def test_an_old_file_is_read_once(tmp_path, monkeypatch):
    path = str(tmp_path / "check.py")
    _write(path, "print(1)")
    monkeypatch.setattr(validation, "RACY_SECONDS", 0.0)
    cache = {}
    first = inputs_digest([path], cache=cache)
    assert len(cache) == 1
    # Proof the file is not read again: a planted digest comes back.
    key = next(iter(cache))
    cache[key] = "planted"
    assert list(inputs_digest([path], cache=cache).values()) == ["planted"]
    _write(path, "print(22)")
    assert inputs_digest([path], cache=cache) != first


def test_a_young_file_is_always_read(tmp_path):
    """Same size, same timestamp tick: only reading it can tell (racy clean)."""
    path = str(tmp_path / "check.py")
    _write(path, "print(1)")
    cache = {}
    before = inputs_digest([path], cache=cache)
    assert cache == {}
    stat = os.stat(path)
    _write(path, "print(2)")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert inputs_digest([path], cache=cache) != before


def test_a_directory_reuses_its_files_digests(tmp_path, monkeypatch):
    tree = tmp_path / "venv"
    tree.mkdir()
    _write(str(tree / "a.py"), "a")
    _write(str(tree / "b.py"), "b")
    monkeypatch.setattr(validation, "RACY_SECONDS", 0.0)
    cache = {}
    first = inputs_digest([str(tree)], cache=cache)
    assert len(cache) == 2
    assert inputs_digest([str(tree)], cache=cache) == first
    _write(str(tree / "b.py"), "bb")
    assert inputs_digest([str(tree)], cache=cache) != first


def test_no_cache_reads_every_file(tmp_path, monkeypatch):
    path = str(tmp_path / "check.py")
    _write(path, "print(1)")
    monkeypatch.setattr(validation, "RACY_SECONDS", 0.0)
    assert inputs_digest([path], cache=None) == inputs_digest([path], cache=None)
