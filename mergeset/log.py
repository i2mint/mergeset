"""The evaluation log: append-only JSONL, and the single source of truth.

Every expensive evaluation is written here once and never re-run. The log also
carries the *monotone closure*: because good sets are (approximately) downward
closed, a passing set marks all of its subsets known-good, and a failing set
marks all of its supersets known-bad. That closure is computed lazily from the
stored rows rather than materialized, so the file stays small and honest.

Monotonicity is a strong prior, not a law: a change may contain the fix that
makes another change work, and flaky tests break it outright. Violations are
detected and reported (:meth:`EvaluationLog.monotonicity_violations`) instead of
being silently trusted.

A row is an answer about *commits*, not about ids. Once the log is pinned
(:meth:`EvaluationLog.pin`) to the base and the head of each change in play,
only rows evaluated against those same commits count — rows about an older head
of a rewritten branch are kept on disk and in :attr:`EvaluationLog.rows`, and
simply not matched (i2mint/mergeset#23). The same holds for *what* was run:
rows judged by another validator (another command, other stages) are kept and
not matched (i2mint/mergeset#32).
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
)

from mergeset.base import (
    UNKNOWN_FINGERPRINT,
    ChangeId,
    ChangeSet,
    Evaluation,
    Verdict,
    set_key,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JsonlLines:
    """Append-only sequence of JSON objects backed by one file.

    The default persistence seam of :class:`EvaluationLog`. Any object with
    ``append(jdict)`` and ``__iter__() -> Iterable[jdict]`` can replace it (an
    in-memory list, a ``dol`` store, a database table).

    >>> import tempfile, os
    >>> path = os.path.join(tempfile.mkdtemp(), 'x.jsonl')
    >>> lines = JsonlLines(path)
    >>> lines.append({'a': 1}); lines.append({'a': 2})
    >>> [d['a'] for d in lines]
    [1, 2]
    """

    def __init__(self, path: str):
        self.path = str(path)
        parent = os.path.dirname(os.path.abspath(self.path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    def append(self, jdict: dict) -> None:
        """Append one record, flushing immediately (crash-safe enough)."""
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(jdict, sort_keys=True) + "\n")

    def __iter__(self) -> Iterator[dict]:
        if not os.path.exists(self.path):
            return iter(())
        with open(self.path, "r", encoding="utf-8") as f:
            return iter([json.loads(line) for line in f if line.strip()])

    def __len__(self) -> int:
        return sum(1 for _ in self)


class StoreLines:
    r"""Lines backed by one key of a ``MutableMapping`` — the non-file backend.

    :class:`JsonlLines` is the right thing over a filesystem: ``open(..., 'a')``
    is a true append. An object store has no append, so this reads, concatenates
    and writes back. That is honest about the cost rather than pretending, and it
    is what lets the evaluation log — the source of truth — reach S3 through the
    same seam as everything else.

    A missing key reads as empty rather than raising, so a first run works.

    >>> backing = {}
    >>> lines = StoreLines(backing, 'run.jsonl')
    >>> list(lines)
    []
    >>> lines.append({'a': 1}); lines.append({'a': 2})
    >>> [d['a'] for d in lines]
    [1, 2]
    >>> backing['run.jsonl']
    '{"a": 1}\n{"a": 2}\n'
    """

    def __init__(self, store, key: str):
        self.store = store
        self.key = key

    def _text(self) -> str:
        try:
            return self.store[self.key]
        except KeyError:
            return ""

    def append(self, jdict: dict) -> None:
        """Append one record by rewriting the value (no append primitive here)."""
        self.store[self.key] = self._text() + json.dumps(jdict, sort_keys=True) + "\n"

    def __iter__(self) -> Iterator[dict]:
        return iter(
            [json.loads(line) for line in self._text().splitlines() if line.strip()]
        )

    def __len__(self) -> int:
        return sum(1 for _ in self)


class MemoryLines(list):
    """In-memory stand-in for :class:`JsonlLines` (tests, dry runs)."""

    def append(self, jdict: dict) -> None:  # noqa: D102 - list.append with a name
        list.append(self, jdict)


@dataclass(frozen=True)
class Known:
    """What the log already knows about a set, without re-evaluating it."""

    verdict: Optional[Verdict]  # None == unknown
    #: The recorded evaluation, when the set itself was evaluated.
    exact: Optional[Evaluation] = None
    #: The witness set that implied the verdict, when it was inferred.
    witness: Optional[ChangeSet] = None

    def __bool__(self) -> bool:
        return self.verdict is not None


@dataclass(frozen=True)
class Pins:
    """What a question is about: the base, each change's head sha, the validator.

    A row *matches* when it was merged onto the same base and every change it
    holds is in play with the same head. A row holding a change that is not in
    play does not match: its head for that change is unchecked, and such a row
    would otherwise surface as an "established" set recommending a change
    nobody asked about, or as a monotonicity violation between two heads of it.

    >>> from mergeset.base import Evaluation, Verdict
    >>> pins = Pins('B', {'a': 'A1', 'b': 'B1'})
    >>> row = Evaluation(frozenset('ab'), Verdict.PASS,
    ...                  base_sha='B', heads={'a': 'A1', 'b': 'B1'})
    >>> pins.matches(row)
    True
    >>> pins.matches(replace(row, heads={'a': 'A0', 'b': 'B1'}))  # a rewritten
    False
    >>> pins.matches(replace(row, base_sha='B0'))                 # base moved
    False
    >>> Pins('B', {'a': 'A1'}).matches(row)          # b is not in play
    False

    With a ``validator`` fingerprint, a row must also have been judged by that
    validator. A row recording none (written before i2mint/mergeset#32) is not
    refuted, only incomplete: see :attr:`EvaluationLog.unpinned`.

    >>> pins = Pins('B', {'a': 'A1', 'b': 'B1'}, validator='command:1')
    >>> pins.matches(replace(row, validator='command:1'))
    True
    >>> pins.refutes(replace(row, validator='command:2'))   # the command changed
    True
    >>> pins.matches(row), pins.refutes(row)                # recorded no validator
    (False, False)
    """

    base: str
    heads: Mapping[ChangeId, str]
    #: Fingerprint of the validator the question is asked of (``'unknown'``
    #: when it cannot say what it runs). ``None`` compares no validator at all.
    validator: Optional[str] = None

    def _same_commits(self, evaluation: Evaluation) -> bool:
        if evaluation.base_sha != self.base:
            return False
        recorded = evaluation.heads
        return all(
            cid in self.heads and recorded.get(cid) == self.heads[cid]
            for cid in evaluation.subset
        )

    def refutes(self, evaluation: Evaluation) -> bool:
        """True iff what ``evaluation`` records shows it answers another question.

        Other commits, or another validator. A row that records too little to
        tell is not refuted -- it is incomplete (see :meth:`complete`).
        """
        if evaluation.pinned and not self._same_commits(evaluation):
            return True
        return (
            self.validator is not None
            and evaluation.validator is not None
            and evaluation.validator != self.validator
        )

    def complete(self, evaluation: Evaluation) -> bool:
        """True iff ``evaluation`` records everything these pins compare."""
        return evaluation.pinned and (
            self.validator is None or evaluation.validator is not None
        )

    def matches(self, evaluation: Evaluation) -> bool:
        """True iff ``evaluation`` was run against these commits, by this validator."""
        return self.complete(evaluation) and not self.refutes(evaluation)

    def stamp(self, evaluation: Evaluation) -> Evaluation:
        """``evaluation`` pinned to these commits and validator, where it is not.

        Pins naming no validator stamp :data:`~mergeset.base.UNKNOWN_FINGERPRINT`,
        never nothing: a row recording no validator reads as written before
        validators were recorded, and ``trust_unpinned`` would adopt it.
        """
        if not evaluation.pinned:
            heads = {c: self.heads[c] for c in evaluation.subset if c in self.heads}
            evaluation = replace(evaluation, base_sha=self.base, heads=heads)
        if evaluation.validator is None:
            evaluation = replace(
                evaluation, validator=self.validator or UNKNOWN_FINGERPRINT
            )
        return evaluation


class EvaluationLog:
    """Append-only record of evaluations, plus the monotone closure over it.

    Args:
        store: Persistence seam. A path (str/PathLike) is wrapped in
            :class:`JsonlLines`; pass :class:`StoreLines` to put the log in an
            artifact store (S3 and friends), or :class:`MemoryLines` for an
            ephemeral log. With no argument at all the log goes to the artifact
            store's ``evaluations/adhoc.jsonl`` — never the working directory.
        pins: The commits the questions are about (see :class:`Pins` and
            :meth:`pin`). Unpinned, every row counts, as before pinning existed;
            :func:`mergeset.analyze` always pins.
        trust_unpinned: Let rows that record no commits at all (written before
            i2mint/mergeset#23, or by an unpinned log), or no validator while
            the pins name one (written before i2mint/mergeset#32), count as
            matches once the log is pinned. Off by default, because such a row
            may be about a head that has since moved, or judged by a command
            that has since changed — which is the defect pinning exists to
            close. Turn it on only when you know neither has changed since those
            rows were written; it is the migration path for an old log. A row
            whose recorded commits or validator differ never counts.

    >>> log = EvaluationLog(MemoryLines())
    >>> from mergeset.base import Evaluation, Verdict
    >>> _ = log.record(Evaluation(frozenset({'a', 'b'}), Verdict.PASS))
    >>> bool(log.known(frozenset({'a'})))          # subset of a passing set
    True
    >>> log.known(frozenset({'a'})).verdict.value
    'pass'
    >>> _ = log.record(Evaluation(frozenset({'c', 'd'}), Verdict.FAIL))
    >>> log.known(frozenset({'a', 'c', 'd'})).verdict.value   # superset of a failing set
    'fail'
    >>> log.known(frozenset({'a', 'c'})).verdict is None
    True
    """

    def __init__(
        self,
        store: Any = None,
        *,
        pins: Optional[Pins] = None,
        trust_unpinned: bool = False,
    ):
        if store is None:
            # Never ``./evaluations.jsonl``: that writes derived data into
            # whatever repository the caller happens to be standing in, which is
            # the default this package exists to have removed.
            from mergeset.storage import artifact_path

            store = JsonlLines(artifact_path("evaluations", "adhoc.jsonl"))
        elif isinstance(store, (str, os.PathLike)):
            store = JsonlLines(str(store))
        self.store = store
        self._trust_unpinned = trust_unpinned
        #: Every row, in log order, whatever commits it is about. Shared with
        #: every view made by :meth:`pinned`, so a row recorded through one
        #: is in all of them, and each decides for itself whether it counts.
        self._rows: List[Evaluation] = [Evaluation.from_jdict(d) for d in self.store]
        self.pins: Optional[Pins] = pins
        self._view: List[Evaluation] = []
        self._view_of = -1  # len(self._rows) when _view was computed

    # -- pinning -----------------------------------------------------------

    def pinned(
        self,
        *,
        base: str,
        heads: Mapping[ChangeId, str],
        validator: Optional[str] = None,
        trust_unpinned: Optional[bool] = None,
    ) -> "EvaluationLog":
        """A view of this log scoped to ``base``, these heads and ``validator``.

        Same store, same rows; this log itself is left as it was, so a caller
        that hands one log to two analyses keeps its own view of it.

        >>> from mergeset.base import Evaluation, Verdict
        >>> log = EvaluationLog(MemoryLines())
        >>> view = log.pinned(base='B', heads={'a': 'A1'})
        >>> _ = view.record(Evaluation(frozenset('a'), Verdict.PASS))
        >>> log.pins is None, len(log), len(view)
        (True, 1, 1)
        >>> len(log.pinned(base='B', heads={'a': 'A2'}))
        0
        """
        view = copy.copy(self)
        view._view_of = -1
        if trust_unpinned is not None:
            view.trust_unpinned = trust_unpinned
        return view.pin(base=base, heads=heads, validator=validator)

    def pin(
        self,
        *,
        base: str,
        heads: Mapping[ChangeId, str],
        validator: Optional[str] = None,
    ) -> "EvaluationLog":
        """Scope *this* log to ``base``, these heads and ``validator``; returns ``self``.

        ``validator`` is the fingerprint of what the questions will be asked of
        (:func:`mergeset.validation.fingerprint_of`); ``None`` matches rows on
        commits alone.

        :meth:`pinned` is the same without changing this object.

        From here on, reading (:meth:`known`, :meth:`exact`, the closure,
        iteration, ``len``) sees only rows evaluated against these commits, and
        :meth:`record` stamps new rows with them. Nothing is removed: the other
        rows stay in the store and in :attr:`rows`, and are reported by
        :attr:`stale` and :attr:`unpinned`.

        >>> from mergeset.base import Evaluation, Verdict
        >>> log = EvaluationLog(MemoryLines()).pin(base='B', heads={'a': 'A1'})
        >>> _ = log.record(Evaluation(frozenset('a'), Verdict.PASS))
        >>> log.known(frozenset('a')).verdict.value
        'pass'
        >>> _ = log.pin(base='B', heads={'a': 'A2'})   # branch a was rewritten
        >>> log.known(frozenset('a')).verdict is None, len(log.rows), len(log.stale)
        (True, 1, 1)
        """
        self.pins = Pins(base, dict(heads), validator)
        self._view_of = -1
        return self

    @property
    def _evaluations(self) -> List[Evaluation]:
        """The rows that count, recomputed when rows were added (by any view)."""
        if self._view_of != len(self._rows):
            self._view = [e for e in self._rows if self._counts(e)]
            self._view_of = len(self._rows)
        return self._view

    def _counts(self, evaluation: Evaluation) -> bool:
        if self.pins is None:
            return True
        if self.pins.refutes(evaluation):
            return False
        if self.pins.complete(evaluation):
            return True
        # It records less than the pins compare (written before #23 or #32).
        if not self.trust_unpinned:
            return False
        # Even trusted, an old row can only speak for changes in play: one
        # holding another change would surface it in a fallback set.
        return evaluation.pinned or evaluation.subset <= self.pins.heads.keys()

    @property
    def trust_unpinned(self) -> bool:
        """Whether rows recording no commits count once the log is pinned."""
        return self._trust_unpinned

    @trust_unpinned.setter
    def trust_unpinned(self, value: bool) -> None:
        self._trust_unpinned = bool(value)
        self._view_of = -1

    @property
    def rows(self) -> List[Evaluation]:
        """Every row in the log, matching the pins or not, in log order."""
        return list(self._rows)

    @property
    def stale(self) -> List[Evaluation]:
        """Rows evaluated against other commits, or by another validator.

        Not wrong — about a different question — so kept, and not matched.
        """
        if self.pins is None:
            return []
        return [e for e in self._rows if self.pins.refutes(e)]

    @property
    def other_validator(self) -> List[Evaluation]:
        """The :attr:`stale` rows judged by a validator other than the pinned one.

        Usually a tier or ``--validate-command`` whose command was edited.
        """
        pinned = self.pins.validator if self.pins is not None else None
        if pinned is None:
            return []
        return [
            e for e in self._rows if e.validator is not None and e.validator != pinned
        ]

    @property
    def unpinned(self) -> List[Evaluation]:
        """Rows recording too little to match that a pinned log is not counting.

        No commits (written before #23), or no validator while the pins name
        one (written before #32). All of them by default; with
        ``trust_unpinned``, only those holding a change that is not in play.
        Empty when the log is unpinned.
        """
        if self.pins is None:
            return []
        return [
            e
            for e in self._rows
            if not self.pins.refutes(e) and not self._counts(e)
        ]

    # -- reading -----------------------------------------------------------

    def __iter__(self) -> Iterator[Evaluation]:
        """The rows that count: all of them, or those matching the pins."""
        return iter(list(self._evaluations))

    def __len__(self) -> int:
        return len(self._evaluations)

    def __bool__(self) -> bool:
        """Always true.

        Without this, ``__len__`` makes an empty log falsy, and every
        ``log = log or EvaluationLog(...)`` silently discards the caller's log
        on the one run where it matters most: the first.
        """
        return True

    @property
    def passing(self) -> List[ChangeSet]:
        """Sets recorded as good, largest first."""
        return sorted(
            (e.subset for e in self._evaluations if e.verdict is Verdict.PASS),
            key=len,
            reverse=True,
        )

    @property
    def failing(self) -> List[ChangeSet]:
        """Sets recorded as bad, smallest first (smallest are the most useful)."""
        return sorted(
            (e.subset for e in self._evaluations if e.verdict is Verdict.FAIL),
            key=len,
        )

    def exact(self, subset: ChangeSet) -> Optional[Evaluation]:
        """The most recent evaluation of exactly this set, if any."""
        for e in reversed(self._evaluations):
            if e.subset == subset and e.verdict in (Verdict.PASS, Verdict.FAIL):
                return e
        return None

    def known(self, subset: ChangeSet) -> Known:
        """What we know about ``subset`` without evaluating it.

        Exact hits win; otherwise the monotone closure decides, preferring the
        cheapest witness (the largest passing superset, the smallest failing
        subset).
        """
        exact = self.exact(subset)
        if exact is not None:
            return Known(exact.verdict, exact=exact)
        for good in self.passing:  # largest first
            if subset <= good:
                return Known(Verdict.PASS, witness=good)
        for bad in self.failing:  # smallest first
            if bad <= subset:
                return Known(Verdict.FAIL, witness=bad)
        return Known(None)

    def minimal_failing_sets(self) -> List[ChangeSet]:
        """Recorded failing sets with no recorded failing proper subset.

        These are the *conflicts* the solver hits. They are minimal with respect
        to what has been observed, which is not necessarily globally minimal —
        the solver shrinks them further with QuickXplain as it goes.
        """
        failing = self.failing
        return [s for s in failing if not any(other < s for other in failing)]

    def maximal_passing_sets(self) -> List[ChangeSet]:
        """Recorded passing sets with no recorded passing proper superset."""
        passing = self.passing
        return [s for s in passing if not any(s < other for other in passing)]

    def monotonicity_violations(self) -> List[Tuple[ChangeSet, ChangeSet]]:
        """``(good, bad)`` pairs where a *subset* of a good set was seen failing.

        A non-empty result means the downward-closure assumption broke here:
        a flaky test, a non-deterministic build, or a change that *fixes*
        another. Reported, never silently smoothed over.
        """
        out = []
        for good in self.passing:
            for bad in self.failing:
                if bad < good or bad == good:
                    out.append((good, bad))
        return out

    # -- writing -----------------------------------------------------------

    def record(self, evaluation: Evaluation) -> Evaluation:
        """Append ``evaluation`` and return it.

        ``at`` is stamped if absent, and so are the pinned commits: a row that
        does not say what it was run against cannot be told apart from one
        about a branch that has since been rewritten.
        """
        if evaluation.at is None:
            evaluation = replace(evaluation, at=_now())
        if self.pins is not None:
            evaluation = self.pins.stamp(evaluation)
        self.store.append(evaluation.to_jdict())
        self._rows.append(evaluation)
        return evaluation

    def caching(self, evaluate: Callable[[ChangeSet], Evaluation]):
        """Wrap ``evaluate`` so known sets are answered from the log.

        The returned callable is what the solver should be handed: it never
        spends a real evaluation on a set the log can already decide.
        """

        def cached(subset: ChangeSet) -> Evaluation:
            known = self.known(subset)
            if known:
                if known.exact is not None:
                    return replace(known.exact, cached=True)
                return Evaluation(
                    subset=subset,
                    verdict=known.verdict,
                    note=f"inferred from {set_key(known.witness)}",
                    cached=True,
                )
            return self.record(evaluate(subset))

        return cached


def sets_evaluated(log: EvaluationLog) -> Iterable[Tuple[Tuple[str, ...], str]]:
    """Yield ``(sorted ids, verdict)`` for every row — handy for reports."""
    for e in log:
        yield set_key(e.subset), e.verdict.value
