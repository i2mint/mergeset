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
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator, List, Optional, Tuple

from mergeset.base import ChangeSet, Evaluation, Verdict, set_key


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


class EvaluationLog:
    """Append-only record of evaluations, plus the monotone closure over it.

    Args:
        store: Persistence seam. A path (str/PathLike) is wrapped in
            :class:`JsonlLines`; pass :class:`StoreLines` to put the log in an
            artifact store (S3 and friends), or :class:`MemoryLines` for an
            ephemeral log. With no argument at all the log goes to the artifact
            store's ``evaluations/adhoc.jsonl`` — never the working directory.

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

    def __init__(self, store: Any = None):
        if store is None:
            # Never ``./evaluations.jsonl``: that writes derived data into
            # whatever repository the caller happens to be standing in, which is
            # the default this package exists to have removed.
            from mergeset.storage import artifact_path

            store = JsonlLines(artifact_path("evaluations", "adhoc.jsonl"))
        elif isinstance(store, (str, os.PathLike)):
            store = JsonlLines(str(store))
        self.store = store
        self._evaluations: List[Evaluation] = [
            Evaluation.from_jdict(d) for d in self.store
        ]

    # -- reading -----------------------------------------------------------

    def __iter__(self) -> Iterator[Evaluation]:
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
        """Append ``evaluation`` (stamping ``at`` if absent) and return it."""
        if evaluation.at is None:
            evaluation = Evaluation(
                subset=evaluation.subset,
                verdict=evaluation.verdict,
                stage=evaluation.stage,
                merge=evaluation.merge,
                validation=evaluation.validation,
                duration=evaluation.duration,
                at=_now(),
                note=evaluation.note,
            )
        self.store.append(evaluation.to_jdict())
        self._evaluations.append(evaluation)
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
