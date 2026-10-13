"""Input digests do not block on a FIFO, and a missing pytest is a refusal (#51)."""

import os
import shutil
import sys
import threading

import pytest

import mergeset.cli as cli
import mergeset.validation as validation
from mergeset.base import CapabilityError
from mergeset.validation import inputs_digest, pytest_validation

from test_cli_tiers import _captured


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs POSIX FIFOs")
def test_a_file_replaced_by_a_fifo_between_stat_and_open_does_not_block(
    tmp_path, monkeypatch
):
    fifo = str(tmp_path / "input.py")
    os.mkfifo(fifo)
    regular = tmp_path / "other.py"
    regular.write_text("print(1)")
    real_stat = os.stat
    # What `stat` saw a moment before the swap: a regular file.
    monkeypatch.setattr(
        validation.os,
        "stat",
        lambda p, *a, **k: real_stat(regular if p == fifo else p, *a, **k),
    )
    result = {}
    worker = threading.Thread(
        target=lambda: result.update(inputs_digest([fifo], cache=None)), daemon=True
    )
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "opening the FIFO blocked"
    assert list(result.values()) == ["missing"]


def test_the_cache_key_is_the_opened_files_own_stat(tmp_path, monkeypatch):
    path = tmp_path / "check.py"
    path.write_text("print(1)")
    monkeypatch.setattr(validation, "RACY_SECONDS", 0.0)  # trust it at once
    cache = {}
    inputs_digest([str(path)], cache=cache)
    (key,) = cache
    opened = os.stat(path)
    assert key[1:] == (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_ctime_ns,
    )


def test_the_default_cache_shows_by_name_in_a_signature():
    import inspect

    assert "FILE_DIGESTS" in str(inspect.signature(inputs_digest))
    assert "object object" not in str(inspect.signature(inputs_digest))


def test_a_missing_pytest_is_a_refusal_not_a_traceback(tmp_path):
    validate = pytest_validation(env={"PATH": str(tmp_path)})
    with pytest.raises(CapabilityError, match="pytest.*not on PATH"):
        validate(str(tmp_path))


def test_a_vanished_worktree_is_still_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        validation._run(
            [sys.executable, "-c", "pass"],
            str(tmp_path / "gone"),
            timeout=None,
            env=None,
        )


def test_the_cli_refuses_when_pytest_is_missing(repo, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))  # git yes, pytest no
    monkeypatch.setenv("PATH", str(bin_dir))
    out = cli.branches(["feat-b", "feat-d"], repo=repo, base="main")
    assert "cannot run yet" in str(out) and "pytest" in str(out)


def test_two_bare_tiers_are_refused_before_a_validator_is_built(repo, monkeypatch):
    _captured(monkeypatch)
    built = []
    monkeypatch.setattr(cli, "_validator", lambda **kw: built.append(kw))
    out = cli.branches(["feat-a"], repo=repo, base="main", tier=["unit", "e2e"])
    assert "Only one --tier can be a bare name" in str(out)
    assert built == []
