"""The agent skill that ships inside the package, and how to install it.

``mergeset`` bundles an `Agent Skill <https://agentskills.io>`_ — the operating
instructions an AI agent needs to drive this tool well: which oracle to ask
first, what a report does *not* mean, and what must never be committed. It is
real files inside the installed package, so ``pip install mergeset`` already
delivers it::

    >>> (skills_dir() / 'mergeset' / 'SKILL.md').is_file()
    True

Agent hosts do not read the package, though — they read their own skills
directory. :func:`install_skills` bridges the two:

.. code-block:: bash

    mergeset install-skills                            # -> ~/.claude/skills
    mergeset install-skills --target ~/.agents/skills  # any host's directory

The default is a symlink, so ``pip install -U mergeset`` updates the installed
skill too. Every part is one keyword argument away from being replaced: where
the skills come from (``skills_root``), where they go (``target``), and whether
the link is a symlink or a copy (``link``).
"""

import os
import shutil
from pathlib import Path
from typing import Iterator, List, Optional

from mergeset.base import MergesetError

#: Where an agent host looks by default. Overridden per call, or per host.
DEFAULT_TARGET = "~/.claude/skills"


def skills_dir() -> Path:
    """The directory of skills bundled inside the installed package.

    >>> skills_dir().name
    'skills'
    """
    return Path(__file__).resolve().parent / "data" / "skills"


def bundled_skills(skills_root: Optional[str] = None) -> Iterator[Path]:
    """Yield the directory of every bundled skill (each holding a ``SKILL.md``).

    ``skills_root`` is resolved, so a relative one still yields links that work
    from anywhere.

    >>> [p.name for p in bundled_skills()]
    ['mergeset']
    """
    root = Path(skills_root).expanduser().resolve() if skills_root else skills_dir()
    if not root.is_dir():
        raise MergesetError(f"No such skills directory: {root}")
    yield from sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file())


def install_skills(
    target: str = DEFAULT_TARGET,
    *,
    skills_root: Optional[str] = None,
    link: bool = True,
    overwrite: bool = False,
) -> List[str]:
    """Put the bundled skills where an agent host will find them.

    Returns the destination path of every skill installed. A destination that
    already holds a skill is left alone, so re-running is safe and an edited
    skill is never silently replaced — and anything *else* sitting in the way
    (a file, a stale broken link) raises rather than being reported as fine.

    ``overwrite=True`` is the escape hatch, and it is not gentle: it deletes
    whatever is at the destination, including a directory someone kept notes in.

    >>> import tempfile
    >>> dest = tempfile.mkdtemp()
    >>> installed = install_skills(dest)
    >>> [Path(p).name for p in installed]
    ['mergeset']
    >>> Path(installed[0], 'SKILL.md').read_text().startswith('---')
    True
    >>> install_skills(dest)          # already there, nothing to do
    []
    """
    target_dir = Path(target).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for source in bundled_skills(skills_root):
        destination = target_dir / source.name
        if _holds_a_skill(destination):
            if not overwrite:
                continue
        elif destination.exists() or destination.is_symlink():
            if not overwrite:
                raise MergesetError(
                    f"{destination} is in the way and is not a skill. "
                    f"Move it, or pass overwrite=True (--overwrite) to replace it."
                )
        if destination.exists() or destination.is_symlink():
            _remove(destination)
        if link:
            destination.symlink_to(source, target_is_directory=True)
        else:
            shutil.copytree(source, destination)
        installed.append(str(destination))
    return installed


def _holds_a_skill(path: Path) -> bool:
    """Is there already a usable skill at this destination?"""
    return (path / "SKILL.md").is_file()


def _remove(path: Path) -> None:
    """Delete a skill destination, whether symlink, file or real tree."""
    if path.is_symlink():
        try:
            path.unlink()
        except OSError:  # a directory symlink on Windows needs rmdir, not unlink
            os.rmdir(path)
    elif path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)
