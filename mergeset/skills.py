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

    mergeset install-skills                      # -> ~/.claude/skills/mergeset
    mergeset install-skills ~/.agents/skills     # any host's directory

The default is a symlink, so ``pip install -U mergeset`` updates the installed
skill too. Every part is one keyword argument away from being replaced: where
the skills come from (``skills_root``), where they go (``target``), and whether
the link is a symlink or a copy (``link``).
"""

import os
import shutil
from pathlib import Path
from typing import Iterator, List, Optional

#: Where an agent host looks by default. Overridden per call, or per host.
DEFAULT_TARGET = "~/.claude/skills"


def skills_dir() -> Path:
    """The directory of skills bundled inside the installed package.

    This is also the entry point registered under ``skill.skill_packs``, so
    tooling that indexes skill packs finds mergeset's without installing it.

    >>> skills_dir().name
    'skills'
    """
    return Path(__file__).resolve().parent / "data" / "skills"


def bundled_skills(skills_root: Optional[str] = None) -> Iterator[Path]:
    """Yield the directory of every bundled skill (each holding a ``SKILL.md``).

    >>> [p.name for p in bundled_skills()]
    ['mergeset']
    """
    root = Path(skills_root).expanduser() if skills_root else skills_dir()
    yield from sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file())


def install_skills(
    target: str = DEFAULT_TARGET,
    *,
    skills_root: Optional[str] = None,
    link: bool = True,
    overwrite: bool = False,
) -> List[str]:
    """Put the bundled skills where an agent host will find them.

    Returns the destination path of every skill installed. An existing
    destination is left alone unless ``overwrite`` is set, so re-running is
    safe and never silently replaces a skill someone edited.

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
    target_dir = Path(os.path.expanduser(target))
    target_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for source in bundled_skills(skills_root):
        destination = target_dir / source.name
        if destination.exists() or destination.is_symlink():
            if not overwrite:
                continue
            _remove(destination)
        if link:
            destination.symlink_to(source, target_is_directory=True)
        else:
            shutil.copytree(source, destination)
        installed.append(str(destination))
    return installed


def _remove(path: Path) -> None:
    """Delete a skill destination, whether it is a symlink or a real tree."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)
