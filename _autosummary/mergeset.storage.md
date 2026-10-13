# mergeset.storage

Where mergeset’s artifacts live, and how code reaches them.

Everything mergeset produces — reports, evaluation logs, raw validation output,
captured failure fixtures — is *derived data*. It has a different lifecycle from
code and, crucially, a different **provenance**: it is captured from whatever
repository was analysed, which is very often private. So none of it belongs in a
repository, and the default location makes sure it never lands in one by
accident:

```default
~/.local/share/mergeset/<kind>/          (%LOCALAPPDATA% on Windows)
```

Four kinds, four sub-stores:

| `reports`     | Rendered analyses — `<name>/REPORT.md`, `<name>/report.html`   |
|---------------|----------------------------------------------------------------|
| `evaluations` | The append-only JSONL evaluation logs (the source of truth)    |
| `logs`        | Raw build/test/lint output captured during validation          |
| `fixtures`    | Captured failure output kept as regression tests               |

Each store is a plain [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping) of `str -> str`,
so business logic never learns where the bytes physically are:

```default
>>> import tempfile
>>> mall = artifact_mall(rootdir=tempfile.mkdtemp())
>>> sorted(mall)
['evaluations', 'fixtures', 'logs', 'reports']
>>> reports = mall['reports']
>>> reports['demo/REPORT.md'] = '# hello'
>>> reports['demo/REPORT.md']
'# hello'
>>> list(reports)
['demo/REPORT.md']
```

The backend is one keyword argument (`store_factory`), so pointing the same
code at S3 is a one-line change and no caller notices:

```default
from s3dol import S3Store
mall = artifact_mall(
    store_factory=lambda kind, root, binary=False: S3Store(bucket, prefix=kind)
)
```

A factory is handed the **kind and the root separately**, never a joined
filesystem path — a backend that has no filesystem must not have to parse one
out, and on Windows a joined path would put backslashes in S3 keys.

The root is overridden by one environment variable, `MERGESET_DATA_DIR` — one
knob for the root, never one per kind.

### Module Attributes

| [`ARTIFACT_KINDS`](#mergeset.storage.ARTIFACT_KINDS)   | The kinds of artifact mergeset produces.   |
|-------------------------------------------------------------------|--------------------------------------------|
| [`StoreFactory`](#mergeset.storage.StoreFactory)     | `(kind, rootdir, *, binary) -> store`.     |

### Functions

| [`app_data_rootdir`](#mergeset.storage.app_data_rootdir)(\*[, app_name, envvar])           | The artifact root for `app_name`, honouring `$MERGESET_DATA_DIR`.   |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| [`artifact_mall`](#mergeset.storage.artifact_mall)(\*[, rootdir, store_factory, ...])   | All the artifact stores, keyed by kind — a *mall*, in `dol` terms.  |
| [`artifact_path`](#mergeset.storage.artifact_path)(kind[, key, rootdir, app_name])      | Filesystem path for `kind`/`key` under the *local* artifact root.   |
| [`artifact_store`](#mergeset.storage.artifact_store)(kind, \*[, rootdir, ...])           | A store for one kind of artifact — `str` values, or `bytes`.        |
| [`evaluation_lines`](#mergeset.storage.evaluation_lines)(repo, \*[, store, rootdir, ...])  | The append-only lines object backing this repo's evaluation log.    |
| [`evaluation_log_path`](#mergeset.storage.evaluation_log_path)(repo, \*[, rootdir, app_name]) | Default evaluation-log path for `repo` — in the artifact store.     |
| [`run_key`](#mergeset.storage.run_key)(repo, \*[, at])                            | A key naming one run of one repository: `<repo-slug>/<timestamp>`.  |
| [`slash_separated_keys`](#mergeset.storage.slash_separated_keys)(store, \*[, sep])             | Make `/` the key separator whatever the platform's is.              |
| [`slugify`](#mergeset.storage.slugify)(text, \*[, maxlen])                        | A filesystem-safe key naming a run after its repository.            |

### mergeset.storage.ARTIFACT_KINDS *: [Tuple](https://docs.python.org/3/library/typing.html#typing.Tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('reports', 'evaluations', 'logs', 'fixtures')*

The kinds of artifact mergeset produces. One sub-store each; never write to
the root itself, so a fifth kind costs no migration.

### mergeset.storage.StoreFactory

`(kind, rootdir, *, binary) -> store`.
Kind and root are passed separately on purpose — see the module docstring.
`binary` says whether the values are `bytes` (a PDF) or `str` (a report,
a log, a JSONL line). A backend has to know which; it is not a detail the
caller can paper over.

* **Type:**
  What a `store_factory` must be

alias of `Callable`[[…], [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)]

### mergeset.storage.app_data_rootdir(, app_name='mergeset', envvar='MERGESET_DATA_DIR')

The artifact root for `app_name`, honouring `$MERGESET_DATA_DIR`.

It is a *root*, not a leaf: artifacts always go in a per-kind subfolder of
it (see [`artifact_store()`](#mergeset.storage.artifact_store)), so a new kind never needs a migration.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> import os, tempfile
>>> d = tempfile.mkdtemp()
>>> os.environ['MERGESET_DATA_DIR'] = d
>>> app_data_rootdir() == d
True
>>> del os.environ['MERGESET_DATA_DIR']
>>> app_data_rootdir().endswith('mergeset')
True
```

### mergeset.storage.artifact_mall(, rootdir=None, store_factory=None, kinds=('reports', 'evaluations', 'logs', 'fixtures'), app_name='mergeset', binary=False)

All the artifact stores, keyed by kind — a *mall*, in `dol` terms.

Stores are built lazily, so asking for the mall never creates a directory
for a kind you do not use.

* **Return type:**
  [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)]

```pycon
>>> import tempfile
>>> mall = artifact_mall(rootdir=tempfile.mkdtemp())
>>> mall['evaluations']['a.jsonl'] = '{}\n'
>>> list(mall['evaluations'])
['a.jsonl']
```

### mergeset.storage.artifact_path(kind, key='', , rootdir=None, app_name='mergeset')

Filesystem path for `kind`/`key` under the *local* artifact root.

The escape hatch for the things that genuinely need a path rather than a
store — the append-only evaluation log, and a subprocess told where to write
its own output. Everything else should go through [`artifact_store()`](#mergeset.storage.artifact_store),
because a path is exactly the coupling the store exists to remove.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> import tempfile
>>> root = tempfile.mkdtemp()
>>> artifact_path('evaluations', 'x.jsonl', rootdir=root) == \
...     __import__('os').path.join(root, 'evaluations', 'x.jsonl')
True
```

### mergeset.storage.artifact_store(kind, , rootdir=None, store_factory=None, app_name='mergeset', binary=False)

A store for one kind of artifact — `str` values, or `bytes`.

* **Parameters:**
  * **kind** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – One of [`ARTIFACT_KINDS`](#mergeset.storage.ARTIFACT_KINDS) (any name works; the tuple is the
    set mergeset itself uses).
  * **rootdir** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Artifact root. Defaults to [`app_data_rootdir()`](#mergeset.storage.app_data_rootdir).
  * **store_factory** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)]]) – The backend seam —
    `(kind, rootdir, *, binary) -> MutableMapping`, defaulting to
    `dol` files under `<rootdir>/<kind>/`. Swap it for S3, a
    database, or a dict without touching a single caller.
  * **binary** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Values are `bytes` rather than `str`. A run’s PDF and its
    Markdown share one directory and differ only in this flag.
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

```pycon
>>> import tempfile
>>> store = artifact_store('logs', rootdir=tempfile.mkdtemp())
>>> store['run-1.log'] = 'all green'
>>> store['run-1.log']
'all green'
```

### mergeset.storage.evaluation_lines(repo, , store=None, rootdir=None, app_name='mergeset')

The append-only lines object backing this repo’s evaluation log.

With no `store`, the local filesystem backend is used directly, because
`open(path, 'a')` is a *true* append and re-writing a growing log on every
evaluation is not. With a `store` (S3, a database, a dict), the log goes
through it like every other artifact — the source of truth is not allowed to
be the one thing that cannot leave the filesystem.

```pycon
>>> import tempfile
>>> lines = evaluation_lines('/x/proj/widget', rootdir=tempfile.mkdtemp())
>>> lines.append({'a': 1}); [d['a'] for d in lines]
[1]
```

```pycon
>>> backing = {}
>>> lines = evaluation_lines('/x/proj/widget', store=backing)
>>> lines.append({'a': 1}); list(backing)[0].endswith('.jsonl')
True
```

### mergeset.storage.evaluation_log_path(repo, , rootdir=None, app_name='mergeset')

Default evaluation-log path for `repo` — in the artifact store.

Deliberately **not** `<repo>/.mergeset/evaluations.jsonl`: that writes a
file capturing one repository’s internals into that same repository, which
is how derived data ends up committed.

`repo` is resolved to an absolute path first, so `'.'` names the current
directory rather than collapsing every project into one `repo.jsonl`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> import tempfile, os
>>> p = evaluation_log_path('/x/proj/widget', rootdir=tempfile.mkdtemp())
>>> os.path.basename(p).startswith('proj-widget-')
True
>>> os.path.basename(p).endswith('.jsonl')
True
```

### mergeset.storage.run_key(repo, , at=None)

A key naming one run of one repository: `<repo-slug>/<timestamp>`.

Reports are keyed by run, not by repository, so a second analysis of the
same repo does not overwrite the first. The 18-PR re-run of an earlier
analysis is exactly the case that made this necessary: the interesting thing
about it is the *diff* against the previous run, and there is no diff if the
previous run was clobbered.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> key = run_key('/x/proj/widget', at='2026-09-09T14-00-00Z')
>>> key.endswith('/2026-09-09T14-00-00Z')
True
>>> key.startswith('proj-widget-')
True
```

### mergeset.storage.slash_separated_keys(store, , sep='/')

Make `/` the key separator whatever the platform’s is.

Keys are a store’s public namespace, so they must not change shape with the
operating system: a report written under `'run-a/REPORT.md'` has to read
back under that key on Windows too, and an S3 backend uses `/` regardless.
Without this the same key is two different keys on two machines — the
filesystem leaking through the abstraction the store exists to provide.

A no-op where the separator is already `/`.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)

```pycon
>>> store = slash_separated_keys({}, sep='/')
>>> store['a/b'] = 1; dict(store)
{'a/b': 1}
```

On a backslash platform the *backing* store sees native separators while
callers keep using `/`:

```pycon
>>> backing = {}
>>> store = slash_separated_keys(backing, sep='\\')
>>> store['a/b'] = 1
>>> list(backing)
['a\\b']
>>> list(store), store['a/b']
(['a/b'], 1)
```

### mergeset.storage.slugify(text, , maxlen=48)

A filesystem-safe key naming a run after its repository.

Two path components, not one, so `js/widget` and `py/widget` do
not collide. Two components are still not unique — `/a/b/proj` and
`/c/b/proj` both read as `b-proj` — and two repos sharing one evaluation
log would mix their change ids into one monotone closure, which is a wrong
answer rather than an untidy one. So a short digest of the *full* input is
appended whenever the readable part is not the whole story.

The digest also survives truncation: a long parent directory used to eat the
only component that distinguished anything.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> slugify('/Users/me/proj/i/mergeset')
'i-mergeset-ed5b44'
>>> slugify('git@github.com:i2mint/mergeset.git')
'i2mint-mergeset-b35f45'
>>> slugify('.')
'repo-cdb4ee'
```

Different repositories that read alike still get different keys:

```pycon
>>> slugify('/a/b/proj') != slugify('/c/b/proj')
True
```

And a long parent no longer swallows the name:

```pycon
>>> slugify('/x/' + 'a' * 80 + '/repo').startswith('a')
True
>>> 'repo' in slugify('/x/' + 'a' * 80 + '/repo')
True
```
