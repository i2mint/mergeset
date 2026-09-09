"""Where mergeset's artifacts live, and how code reaches them.

Everything mergeset produces — reports, evaluation logs, raw validation output,
captured failure fixtures — is *derived data*. It has a different lifecycle from
code and, crucially, a different **provenance**: it is captured from whatever
repository was analysed, which is very often private. So none of it belongs in a
repository, and the default location makes sure it never lands in one by
accident::

    ~/.local/share/mergeset/<kind>/          (%LOCALAPPDATA% on Windows)

Four kinds, four sub-stores:

===============  ==========================================================
``reports``      Rendered analyses — ``<name>/REPORT.md``, ``<name>/report.html``
``evaluations``  The append-only JSONL evaluation logs (the source of truth)
``logs``         Raw build/test/lint output captured during validation
``fixtures``     Captured failure output kept as regression tests
===============  ==========================================================

Each store is a plain :class:`~collections.abc.MutableMapping` of ``str -> str``,
so business logic never learns where the bytes physically are::

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

The backend is one keyword argument (``store_factory``), so pointing the same
code at S3 is a one-line change and no caller notices::

    from s3dol import S3Store
    mall = artifact_mall(store_factory=lambda kind: S3Store(bucket, prefix=kind))

The root is overridden by one environment variable, ``MERGESET_DATA_DIR`` — one
knob for the root, never one per kind.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from typing import Callable, Optional, Tuple

DEFAULT_APP_NAME = "mergeset"
ROOTDIR_ENVVAR = "MERGESET_DATA_DIR"

#: The kinds of artifact mergeset produces. One sub-store each; never write to
#: the root itself, so a fifth kind costs no migration.
ARTIFACT_KINDS: Tuple[str, ...] = ("reports", "evaluations", "logs", "fixtures")

#: What a ``store_factory`` must be: a directory -> a ``str``-valued store.
StoreFactory = Callable[[str], MutableMapping]


def _platform_data_home() -> str:
    """The OS's per-user data directory, without importing anything optional."""
    if os.name == "nt":  # Windows
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return base
        return os.path.join(os.path.expanduser("~"), "AppData", "Local")
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return xdg
    return os.path.join(os.path.expanduser("~"), ".local", "share")


def app_data_rootdir(
    *, app_name: str = DEFAULT_APP_NAME, envvar: str = ROOTDIR_ENVVAR
) -> str:
    """The artifact root for ``app_name``, honouring ``$MERGESET_DATA_DIR``.

    It is a *root*, not a leaf: artifacts always go in a per-kind subfolder of
    it (see :func:`artifact_store`), so a new kind never needs a migration.

    >>> import os, tempfile
    >>> d = tempfile.mkdtemp()
    >>> os.environ['MERGESET_DATA_DIR'] = d
    >>> app_data_rootdir() == d
    True
    >>> del os.environ['MERGESET_DATA_DIR']
    >>> app_data_rootdir().endswith('mergeset')
    True
    """
    override = os.environ.get(envvar)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(_platform_data_home(), app_name)


def slash_separated_keys(store: MutableMapping, *, sep: str = os.sep) -> MutableMapping:
    r"""Make ``/`` the key separator whatever the platform's is.

    Keys are a store's public namespace, so they must not change shape with the
    operating system: a report written under ``'run-a/REPORT.md'`` has to read
    back under that key on Windows too, and an S3 backend uses ``/`` regardless.
    Without this the same key is two different keys on two machines — the
    filesystem leaking through the abstraction the store exists to provide.

    A no-op where the separator is already ``/``.

    >>> store = slash_separated_keys({}, sep='/')
    >>> store['a/b'] = 1; dict(store)
    {'a/b': 1}

    On a backslash platform the *backing* store sees native separators while
    callers keep using ``/``:

    >>> backing = {}
    >>> store = slash_separated_keys(backing, sep='\\')
    >>> store['a/b'] = 1
    >>> list(backing)
    ['a\\b']
    >>> list(store), store['a/b']
    (['a/b'], 1)
    """
    if sep == "/":
        return store
    from dol import wrap_kvs

    return wrap_kvs(
        store,
        id_of_key=lambda k: k.replace("/", sep),
        key_of_id=lambda k: k.replace(sep, "/"),
    )


def _text_files_factory(directory: str) -> MutableMapping:
    """The default backend: ``dol.TextFiles`` over a directory, created on demand.

    ``dol`` is the strongest local backend that is already in this ecosystem:
    it has no dependencies of its own and gives relative-path keys, nested keys,
    and the full ``MutableMapping`` surface for free.
    """
    from dol import TextFiles, mk_dirs_if_missing

    os.makedirs(directory, exist_ok=True)
    # ``mk_dirs_if_missing`` is what makes a nested key such as
    # ``'<run>/REPORT.md'`` just work — without it the write fails on the
    # missing intermediate directory.
    return slash_separated_keys(mk_dirs_if_missing(TextFiles(directory)))


def artifact_store(
    kind: str,
    *,
    rootdir: Optional[str] = None,
    store_factory: Optional[StoreFactory] = None,
    app_name: str = DEFAULT_APP_NAME,
) -> MutableMapping:
    """A ``str -> str`` store for one kind of artifact.

    Args:
        kind: One of :data:`ARTIFACT_KINDS` (any name works; the tuple is the
            set mergeset itself uses).
        rootdir: Artifact root. Defaults to :func:`app_data_rootdir`.
        store_factory: The backend seam — ``directory -> MutableMapping``.
            Defaults to ``dol.TextFiles``. Swap it for S3, a database, or a
            dict without touching a single caller.

    >>> import tempfile
    >>> store = artifact_store('logs', rootdir=tempfile.mkdtemp())
    >>> store['run-1.log'] = 'all green'
    >>> store['run-1.log']
    'all green'
    """
    rootdir = rootdir or app_data_rootdir(app_name=app_name)
    factory = store_factory or _text_files_factory
    return factory(os.path.join(rootdir, kind))


def artifact_mall(
    *,
    rootdir: Optional[str] = None,
    store_factory: Optional[StoreFactory] = None,
    kinds: Tuple[str, ...] = ARTIFACT_KINDS,
    app_name: str = DEFAULT_APP_NAME,
) -> Mapping[str, MutableMapping]:
    """All the artifact stores, keyed by kind — a *mall*, in ``dol`` terms.

    Stores are built lazily, so asking for the mall never creates a directory
    for a kind you do not use.

    >>> import tempfile
    >>> mall = artifact_mall(rootdir=tempfile.mkdtemp())
    >>> mall['evaluations']['a.jsonl'] = '{}\\n'
    >>> list(mall['evaluations'])
    ['a.jsonl']
    """
    return _LazyMall(
        kinds=tuple(kinds),
        rootdir=rootdir,
        store_factory=store_factory,
        app_name=app_name,
    )


class _LazyMall(Mapping):
    """A ``Mapping`` of kind -> store that builds each store on first access."""

    def __init__(self, *, kinds, rootdir, store_factory, app_name):
        self._kinds = kinds
        self._rootdir = rootdir
        self._store_factory = store_factory
        self._app_name = app_name
        self._cache: dict = {}

    def __getitem__(self, kind):
        if kind not in self._kinds:
            raise KeyError(
                f"{kind!r} is not a mergeset artifact kind. "
                f"Known kinds: {', '.join(self._kinds)}."
            )
        if kind not in self._cache:
            self._cache[kind] = artifact_store(
                kind,
                rootdir=self._rootdir,
                store_factory=self._store_factory,
                app_name=self._app_name,
            )
        return self._cache[kind]

    def __iter__(self):
        return iter(sorted(self._kinds))

    def __len__(self):
        return len(self._kinds)


def artifact_path(
    kind: str,
    key: str = "",
    *,
    rootdir: Optional[str] = None,
    app_name: str = DEFAULT_APP_NAME,
) -> str:
    """Filesystem path for ``kind``/``key`` under the *local* artifact root.

    The escape hatch for the things that genuinely need a path rather than a
    store — the append-only evaluation log, and a subprocess told where to write
    its own output. Everything else should go through :func:`artifact_store`,
    because a path is exactly the coupling the store exists to remove.

    >>> import tempfile
    >>> root = tempfile.mkdtemp()
    >>> artifact_path('evaluations', 'x.jsonl', rootdir=root) == \\
    ...     __import__('os').path.join(root, 'evaluations', 'x.jsonl')
    True
    """
    rootdir = rootdir or app_data_rootdir(app_name=app_name)
    return os.path.join(rootdir, kind, key) if key else os.path.join(rootdir, kind)


def slugify(text: str, *, maxlen: int = 60) -> str:
    """A filesystem-safe key naming a run after its repository.

    Two path components, not one, so ``c/cosmograph`` and ``py/cosmograph``
    do not collide into the same log.

    >>> slugify('/Users/me/proj/i/mergeset')
    'i-mergeset'
    >>> slugify('git@github.com:i2mint/mergeset.git')
    'i2mint-mergeset'
    >>> slugify('.')
    'repo'
    """
    text = str(text).strip().rstrip("/")
    if text.endswith(".git"):
        text = text[: -len(".git")]
    if ":" in text and "/" in text.rsplit(":", 1)[-1]:  # scp-style remote or URL
        text = text.rsplit(":", 1)[-1]
    parts = [
        p for p in text.replace("\\", "/").split("/") if p and p not in (".", "..")
    ]
    joined = "-".join(parts[-2:])
    safe = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in joined)
    return "-".join(filter(None, safe.split("-")))[:maxlen] or "repo"


def evaluation_log_path(
    repo: str,
    *,
    rootdir: Optional[str] = None,
    app_name: str = DEFAULT_APP_NAME,
) -> str:
    """Default evaluation-log path for ``repo`` — in the artifact store.

    Deliberately **not** ``<repo>/.mergeset/evaluations.jsonl``: that writes a
    file capturing one repository's internals into that same repository, which
    is how derived data ends up committed.

    ``repo`` is resolved to an absolute path first, so ``'.'`` names the current
    directory rather than collapsing every project into one ``repo.jsonl``.

    >>> import tempfile, os
    >>> p = evaluation_log_path('/x/y/cosmograph', rootdir=tempfile.mkdtemp())
    >>> os.path.basename(p)
    'y-cosmograph.jsonl'
    """
    repo = os.path.abspath(os.path.expanduser(str(repo)))
    return artifact_path(
        "evaluations", f"{slugify(repo)}.jsonl", rootdir=rootdir, app_name=app_name
    )
