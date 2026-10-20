# mergeset.skills

The agent skill that ships inside the package, and how to install it.

`mergeset` bundles an [Agent Skill](https://agentskills.io) — the operating
instructions an AI agent needs to drive this tool well: which oracle to ask
first, what a report does *not* mean, and what must never be committed. It is
real files inside the installed package, so `pip install mergeset` already
delivers it:

```default
>>> (skills_dir() / 'mergeset' / 'SKILL.md').is_file()
True
```

Agent hosts do not read the package, though — they read their own skills
directory. [`install_skills()`](#mergeset.skills.install_skills) bridges the two:

```bash
mergeset install-skills                            # -> ~/.claude/skills
mergeset install-skills --target ~/.agents/skills  # any host's directory
```

The default is a symlink, so `pip install -U mergeset` updates the installed
skill too. Every part is one keyword argument away from being replaced: where
the skills come from (`skills_root`), where they go (`target`), and whether
the link is a symlink or a copy (`link`).

### Module Attributes

| [`DEFAULT_TARGET`](#mergeset.skills.DEFAULT_TARGET)   | Where an agent host looks by default.   |
|-------------------------------------------------------------------|-----------------------------------------|

### Functions

| [`bundled_skills`](#mergeset.skills.bundled_skills)([skills_root])                    | Yield the directory of every bundled skill (each holding a `SKILL.md`).   |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`install_skills`](#mergeset.skills.install_skills)([target, skills_root, link, ...]) | Put the bundled skills where an agent host will find them.                |
| [`skills_dir`](#mergeset.skills.skills_dir)()                                     | The directory of skills bundled inside the installed package.             |

### mergeset.skills.DEFAULT_TARGET *= '~/.claude/skills'*

Where an agent host looks by default. Overridden per call, or per host.

### mergeset.skills.bundled_skills(skills_root=None)

Yield the directory of every bundled skill (each holding a `SKILL.md`).

`skills_root` is resolved, so a relative one still yields links that work
from anywhere.

```pycon
>>> [p.name for p in bundled_skills()]
['mergeset']
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### mergeset.skills.install_skills(target='~/.claude/skills', , skills_root=None, link=True, overwrite=False)

Put the bundled skills where an agent host will find them.

Returns the destination path of every skill installed. A destination that
already holds a skill is left alone, so re-running is safe and an edited
skill is never silently replaced — and anything *else* sitting in the way
(a file, a stale broken link) raises rather than being reported as fine.

`overwrite=True` is the escape hatch, and it is not gentle: it deletes
whatever is at the destination, including a directory someone kept notes in.

```pycon
>>> import tempfile
>>> dest = tempfile.mkdtemp()
>>> installed = install_skills(dest)
>>> [Path(p).name for p in installed]
['mergeset']
>>> Path(installed[0], 'SKILL.md').read_text().startswith('---')
True
>>> install_skills(dest)          # already there, nothing to do
[]
```

* **Return type:**
  [`List`](https://docs.python.org/3/library/typing.html#typing.List)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### mergeset.skills.skills_dir()

The directory of skills bundled inside the installed package.

```pycon
>>> skills_dir().name
'skills'
```

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
