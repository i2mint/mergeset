"""Shared fixtures: throwaway git repositories to run real merges against."""

import os
import subprocess
import textwrap

import pytest


def run(repo, *args):
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A repo with: main, two independent branches, and one that conflicts."""
    path = str(tmp_path / "repo")
    os.makedirs(path)
    run(path if False else str(tmp_path), "init", "-q", "-b", "main", path)
    run(path, "config", "user.email", "t@example.com")
    run(path, "config", "user.name", "T")

    def write(name, text):
        with open(os.path.join(path, name), "w") as f:
            f.write(textwrap.dedent(text))

    write("shared.txt", "line one\nline two\nline three\n")
    write("other.txt", "untouched\n")
    run(path, "add", "-A")
    run(path, "commit", "-qm", "base")

    for branch, filename, content in [
        ("feat-a", "shared.txt", "line one\nAAA\nline three\n"),
        ("feat-b", "other.txt", "changed by b\n"),
        ("feat-c", "shared.txt", "line one\nCCC\nline three\n"),
        ("feat-d", "new-d.txt", "d\n"),
    ]:
        run(path, "checkout", "-q", "-b", branch, "main")
        write(filename, content)
        run(path, "add", "-A")
        run(path, "commit", "-qm", f"{branch} change")
        run(path, "checkout", "-q", "main")
    return path


