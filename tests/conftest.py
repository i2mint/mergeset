"""Shared fixtures: throwaway git repositories to run real merges against.

Also the guard that keeps the suite out of the developer's own artifact store.
"""

import os
import subprocess
import sys
import textwrap

import pytest


@pytest.fixture(autouse=True, scope="session")
def _artifacts_go_somewhere_disposable(tmp_path_factory):
    """Point ``$MERGESET_DATA_DIR`` at a temp directory for the whole session.

    Without this, any test that reaches a default — a bare ``EvaluationLog()``,
    an ``analyze()`` with no ``artifacts``, a report with no ``--report-dir`` —
    writes into ``~/.local/share/mergeset/``. One did, and left a real
    evaluation log named after a pytest tmpdir sitting in a real store.

    A test suite that writes outside its own tmpdir is a bug regardless of what
    it writes; in a package whose subject is *where derived data is allowed to
    go*, it is also an embarrassment. The environment variable is the one knob
    for the root, which is exactly what makes this a two-line guard.
    """
    root = tmp_path_factory.mktemp("mergeset-artifacts")
    previous = os.environ.get("MERGESET_DATA_DIR")
    os.environ["MERGESET_DATA_DIR"] = str(root)
    yield root
    if previous is None:
        os.environ.pop("MERGESET_DATA_DIR", None)
    else:
        os.environ["MERGESET_DATA_DIR"] = previous


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


def py_command(tmp_path, name: str, code: str) -> str:
    """A shell command that runs ``code`` with this interpreter, on any platform.

    Stage commands go through the shell, and the shell is ``sh`` on POSIX and
    ``cmd.exe`` on Windows — they share almost no vocabulary. `touch`, `test -f`
    and `!` are all POSIX-only, so a fixture built from them silently reduces a
    regression test to two platforms out of three. Writing the body to a file
    and invoking the interpreter by absolute path avoids the shell entirely
    except for quoting.
    """
    script = tmp_path / f"{name}.py"
    script.write_text(code)
    return f'"{sys.executable}" "{script}"'
