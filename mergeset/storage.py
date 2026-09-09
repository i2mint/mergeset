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
    mall = artifact_mall(
        store_factory=lambda kind, root, binary=False: S3Store(bucket, prefix=kind)
    )

A factory is handed the **kind and the root separately**, never a joined
filesystem path — a backend that has no filesystem must not have to parse one
out, and on Windows a joined path would put backslashes in S3 keys.

The root is overridden by one environment variable, ``MERGESET_DATA_DIR`` — one
knob for the root, never one per kind.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

DEFAULT_APP_NAME = "mergeset"
ROOTDIR_ENVVAR = "MERGESET_DATA_DIR"

#: The kinds of artifact mergeset produces. One sub-store each; never write to
#: the root itself, so a fifth kind costs no migration.
ARTIFACT_KINDS: Tuple[str, ...] = ("reports", "evaluations", "logs", "fixtures")

#: What a ``store_factory`` must be: ``(kind, rootdir, *, binary) -> store``.
#: Kind and root are passed separately on purpose — see the module docstring.
#: ``binary`` says whether the values are ``bytes`` (a PDF) or ``str`` (a report,
#: a log, a JSONL line). A backend has to know which; it is not a detail the
#: caller can paper over.
StoreFactory = Callable[..., MutableMapping]


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


def _files_factory(kind: str, rootdir: str, *, binary: bool = False) -> MutableMapping:
    """The default backend: ``dol`` files under ``<rootdir>/<kind>/``.

    ``dol`` is the strongest local backend already in this ecosystem: no
    dependencies of its own, and relative-path keys, nested keys and the full
    ``MutableMapping`` surface for free. ``Files`` for bytes, ``TextFiles`` for
    text — the same directory either way, so a run's PDF sits beside its
    Markdown.
    """
    from dol import Files, TextFiles, mk_dirs_if_missing

    directory = os.path.join(rootdir, kind)
    os.makedirs(directory, exist_ok=True)
    # ``mk_dirs_if_missing`` is what makes a nested key such as
    # ``'<run>/REPORT.md'`` just work — without it the write fails on the
    # missing intermediate directory.
    cls = Files if binary else TextFiles
    return slash_separated_keys(mk_dirs_if_missing(cls(directory)))


def artifact_store(
    kind: str,
    *,
    rootdir: Optional[str] = None,
    store_factory: Optional[StoreFactory] = None,
    app_name: str = DEFAULT_APP_NAME,
    binary: bool = False,
) -> MutableMapping:
    """A store for one kind of artifact — ``str`` values, or ``bytes``.

    Args:
        kind: One of :data:`ARTIFACT_KINDS` (any name works; the tuple is the
            set mergeset itself uses).
        rootdir: Artifact root. Defaults to :func:`app_data_rootdir`.
        store_factory: The backend seam —
            ``(kind, rootdir, *, binary) -> MutableMapping``, defaulting to
            ``dol`` files under ``<rootdir>/<kind>/``. Swap it for S3, a
            database, or a dict without touching a single caller.
        binary: Values are ``bytes`` rather than ``str``. A run's PDF and its
            Markdown share one directory and differ only in this flag.

    >>> import tempfile
    >>> store = artifact_store('logs', rootdir=tempfile.mkdtemp())
    >>> store['run-1.log'] = 'all green'
    >>> store['run-1.log']
    'all green'
    """
    rootdir = rootdir or app_data_rootdir(app_name=app_name)
    factory = store_factory or _files_factory
    return factory(kind, rootdir, binary=binary)


def artifact_mall(
    *,
    rootdir: Optional[str] = None,
    store_factory: Optional[StoreFactory] = None,
    kinds: Tuple[str, ...] = ARTIFACT_KINDS,
    app_name: str = DEFAULT_APP_NAME,
    binary: bool = False,
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
        binary=binary,
    )


class _LazyMall(Mapping):
    """A ``Mapping`` of kind -> store that builds each store on first access."""

    def __init__(self, *, kinds, rootdir, store_factory, app_name, binary=False):
        self._kinds = kinds
        self._rootdir = rootdir
        self._store_factory = store_factory
        self._app_name = app_name
        self._binary = binary
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
                binary=self._binary,
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


def slugify(text: str, *, maxlen: int = 48) -> str:
    """A filesystem-safe key naming a run after its repository.

    Two path components, not one, so ``js/widget`` and ``py/widget`` do
    not collide. Two components are still not unique — ``/a/b/proj`` and
    ``/c/b/proj`` both read as ``b-proj`` — and two repos sharing one evaluation
    log would mix their change ids into one monotone closure, which is a wrong
    answer rather than an untidy one. So a short digest of the *full* input is
    appended whenever the readable part is not the whole story.

    The digest also survives truncation: a long parent directory used to eat the
    only component that distinguished anything.

    >>> slugify('/Users/me/proj/i/mergeset')
    'i-mergeset-ed5b44'
    >>> slugify('git@github.com:i2mint/mergeset.git')
    'i2mint-mergeset-b35f45'
    >>> slugify('.')
    'repo-cdb4ee'

    Different repositories that read alike still get different keys:

    >>> slugify('/a/b/proj') != slugify('/c/b/proj')
    True

    And a long parent no longer swallows the name:

    >>> slugify('/x/' + 'a' * 80 + '/repo').startswith('a')
    True
    >>> 'repo' in slugify('/x/' + 'a' * 80 + '/repo')
    True
    """
    import hashlib

    original = str(text)
    text = original.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[: -len(".git")]
    if ":" in text and "/" in text.rsplit(":", 1)[-1]:  # scp-style remote or URL
        text = text.rsplit(":", 1)[-1]
    parts = [
        p for p in text.replace("\\", "/").split("/") if p and p not in (".", "..")
    ]
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:6]
    readable = _safe(parts[-1] if parts else "repo")
    parent = _safe(parts[-2]) if len(parts) > 1 else ""
    # Budget the readable half so the digest is never what gets truncated.
    room = maxlen - len(digest) - 1
    if parent:
        readable = f"{parent[: max(1, room - len(readable) - 1)]}-{readable}"
    return f"{readable[:room] or 'repo'}-{digest}"


def _safe(text: str) -> str:
    """Keep only characters every filesystem and object store agrees on."""
    safe = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in text)
    return "-".join(filter(None, safe.split("-")))


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
    >>> p = evaluation_log_path('/x/proj/widget', rootdir=tempfile.mkdtemp())
    >>> os.path.basename(p).startswith('proj-widget-')
    True
    >>> os.path.basename(p).endswith('.jsonl')
    True
    """
    repo = os.path.abspath(os.path.expanduser(str(repo)))
    return artifact_path(
        "evaluations", f"{slugify(repo)}.jsonl", rootdir=rootdir, app_name=app_name
    )


def run_key(repo: str, *, at: Optional[str] = None) -> str:
    """A key naming one run of one repository: ``<repo-slug>/<timestamp>``.

    Reports are keyed by run, not by repository, so a second analysis of the
    same repo does not overwrite the first. The 18-PR re-run of an earlier
    analysis is exactly the case that made this necessary: the interesting thing
    about it is the *diff* against the previous run, and there is no diff if the
    previous run was clobbered.

    >>> key = run_key('/x/proj/widget', at='2026-09-09T14-00-00Z')
    >>> key.endswith('/2026-09-09T14-00-00Z')
    True
    >>> key.startswith('proj-widget-')
    True
    """
    at = at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{slugify(os.path.abspath(os.path.expanduser(str(repo))))}/{at}"


def evaluation_lines(
    repo: str,
    *,
    store: Optional[MutableMapping] = None,
    rootdir: Optional[str] = None,
    app_name: str = DEFAULT_APP_NAME,
):
    """The append-only lines object backing this repo's evaluation log.

    With no ``store``, the local filesystem backend is used directly, because
    ``open(path, 'a')`` is a *true* append and re-writing a growing log on every
    evaluation is not. With a ``store`` (S3, a database, a dict), the log goes
    through it like every other artifact — the source of truth is not allowed to
    be the one thing that cannot leave the filesystem.

    >>> import tempfile
    >>> lines = evaluation_lines('/x/proj/widget', rootdir=tempfile.mkdtemp())
    >>> lines.append({'a': 1}); [d['a'] for d in lines]
    [1]

    >>> backing = {}
    >>> lines = evaluation_lines('/x/proj/widget', store=backing)
    >>> lines.append({'a': 1}); list(backing)[0].endswith('.jsonl')
    True
    """
    from mergeset.log import JsonlLines, StoreLines

    key = f"{slugify(os.path.abspath(os.path.expanduser(str(repo))))}.jsonl"
    if store is None:
        return JsonlLines(evaluation_log_path(repo, rootdir=rootdir, app_name=app_name))
    return StoreLines(store, key)
