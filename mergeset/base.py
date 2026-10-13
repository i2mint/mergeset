"""Core data structures and vocabulary of ``mergeset``.

The unit of work is a **change**: a commit range ``base..head``. Branches, pull
requests and explicit commit lists are merely *sources* that produce changes
(see :mod:`mergeset.sources`). Everything downstream — the evaluation log, the
solver, the report — speaks only of changes, identified by their string ``id``.

A **change set** is a ``frozenset`` of change ids. Sets are the atoms the solver
reasons about; they are serialized as sorted lists so the JSONL log is stable
and diffable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

ChangeId = str
ChangeSet = frozenset  # frozenset[ChangeId]; aliased for readability


def change_set(ids: Iterable[ChangeId]) -> ChangeSet:
    """Normalize any iterable of change ids into a ``frozenset``.

    >>> change_set(['b', 'a', 'b']) == frozenset({'a', 'b'})
    True
    """
    return frozenset(ids)


def set_key(ids: Iterable[ChangeId]) -> tuple:
    """A stable, hashable, JSON-friendly key for a change set.

    >>> set_key({'b', 'a'})
    ('a', 'b')
    """
    return tuple(sorted(ids))


@dataclass(frozen=True)
class Change:
    """One candidate change: everything between ``base`` and ``head``.

    Args:
        id: Short stable identifier, used everywhere else (log, report, CLI).
        head: Commit-ish holding the change (branch name, sha, PR head).
        base: Commit-ish the change is measured against.
        source: Which source produced it (``'branch'``, ``'pr'``, ``'commit'``).
        weight: Cost of *dropping* this change. The solver drops the cheapest
            changes it can when it must drop something, so a high weight means
            "keep me". ``None`` means "let the weighting policy decide".
        meta: Source-specific extras (PR number, author, CI status, draft flag...).

    >>> c = Change(id='fix-a', head='origin/fix-a', base='origin/main')
    >>> c.id, c.source
    ('fix-a', 'branch')
    """

    id: ChangeId
    head: str
    base: str
    source: str = "branch"
    weight: Optional[float] = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def with_weight(self, weight: float) -> "Change":
        """A copy of this change carrying ``weight``."""
        return replace(self, weight=weight)

    def to_jdict(self) -> dict:
        """JSON-able view of the change."""
        return {
            "id": self.id,
            "head": self.head,
            "base": self.base,
            "source": self.source,
            "weight": self.weight,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_jdict(cls, d: Mapping[str, Any]) -> "Change":
        """Inverse of :meth:`to_jdict`."""
        return cls(
            id=d["id"],
            head=d["head"],
            base=d["base"],
            source=d.get("source", "branch"),
            weight=d.get("weight"),
            meta=d.get("meta") or {},
        )


class Verdict(str, Enum):
    """Outcome of evaluating a change set."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"  # the evaluation itself broke; carries no monotone information
    SKIPPED = "skipped"  # budget exhausted


class Stage(str, Enum):
    """Where an evaluation ended."""

    MERGE = "merge"
    VALIDATE = "validate"


@dataclass(frozen=True)
class MergeOutcome:
    """Result of merging a change set onto its base.

    ``reason`` is load-bearing. "These changes conflict with each other" and "we
    could not run the experiment" are completely different facts, and conflating
    them is how a run reports *0 of 15 mergeable, complete* with total
    confidence when the real problem was a bad worktree path. Only
    ``reason == 'conflict'`` may ever enter the conflict set; an ``'error'``
    aborts, because a set that was never tested has told us nothing.
    """

    ok: bool
    #: ``'conflict'`` (a real textual conflict) or ``'error'`` (the merge could
    #: not be attempted: bad path, missing ref, unusable worktree).
    reason: str = "conflict"
    conflicting_files: Sequence[str] = ()
    assisted: bool = False  # resolved by an AI assist rather than cleanly
    assist_diff: Optional[str] = None
    order: Sequence[ChangeId] = ()
    detail: str = ""
    #: The merge commit an assisted resolution produced: base plus every head,
    #: conflicts resolved. A deeper tier checks this commit out instead of
    #: asking the resolver again (i2mint/mergeset#30). Not in :meth:`to_jdict`:
    #: :meth:`Evaluation.to_jdict` stores it beside ``merge``, because releases
    #: before #30 build ``MergeOutcome(**merge)`` and would refuse the log.
    resolved_commit: Optional[str] = None

    def to_jdict(self) -> dict:
        """JSON-able view (without :attr:`resolved_commit`; see there)."""
        return {
            "ok": self.ok,
            "reason": self.reason,
            "conflicting_files": list(self.conflicting_files),
            "assisted": self.assisted,
            "assist_diff": self.assist_diff,
            "order": list(self.order),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class StageRun:
    """What one stage of a staged validation did, and what it cost.

    A stage skipped because its fingerprint matched (an install whose lockfile
    did not change) is recorded too, with ``skipped=True`` and no time: that
    skip is often the largest term in what an evaluation costs, and a log that
    cannot show it cannot confirm it (i2mint/mergeset#17).

    >>> StageRun.from_jdict(StageRun('setup', 33.0, 0).to_jdict())
    StageRun(name='setup', duration=33.0, returncode=0, skipped=False)
    """

    name: str
    duration: float = 0.0
    returncode: Optional[int] = None  # None when skipped
    skipped: bool = False

    def to_jdict(self) -> dict:
        """JSON-able view."""
        return {
            "name": self.name,
            "duration": self.duration,
            "returncode": self.returncode,
            "skipped": self.skipped,
        }

    @classmethod
    def from_jdict(cls, d: Mapping[str, Any]) -> "StageRun":
        """Inverse of :meth:`to_jdict`."""
        return cls(
            name=d["name"],
            duration=d.get("duration") or 0.0,
            returncode=d.get("returncode"),
            skipped=d.get("skipped", False),
        )


@dataclass(frozen=True)
class ValidationOutcome:
    """Result of validating a merged tree."""

    ok: bool
    failing_tests: Sequence[str] = ()
    failing_files: Sequence[str] = ()
    duration: float = 0.0
    stdout_tail: str = ""
    returncode: Optional[int] = None
    #: Per-stage breakdown, in run order, for a staged validator; empty for a
    #: single-command one and on rows written before stages were recorded.
    stages: Sequence[StageRun] = ()

    def __post_init__(self):
        # A tuple whatever was passed, so a recorded outcome equals its re-read.
        object.__setattr__(self, "stages", tuple(self.stages))

    @property
    def stage_seconds(self) -> Dict[str, float]:
        """``{stage name: seconds}`` for the stages that ran (skips excluded).

        The shape :data:`mergeset.cost.Seconds` accepts as a breakdown. Two
        stages sharing a name are summed, never overwritten.

        >>> ValidationOutcome(True, stages=[StageRun('setup', skipped=True),
        ...                                 StageRun('test', 6.0, 0)]).stage_seconds
        {'test': 6.0}
        """
        seconds: Dict[str, float] = {}
        for s in self.stages:
            if not s.skipped:
                seconds[s.name] = seconds.get(s.name, 0.0) + (s.duration or 0.0)
        return seconds

    def to_jdict(self) -> dict:
        """JSON-able view."""
        return {
            "ok": self.ok,
            "failing_tests": list(self.failing_tests),
            "failing_files": list(self.failing_files),
            "duration": self.duration,
            "stdout_tail": self.stdout_tail,
            "returncode": self.returncode,
            "stages": [s.to_jdict() for s in self.stages],
        }

    @classmethod
    def from_jdict(cls, d: Mapping[str, Any]) -> "ValidationOutcome":
        """Inverse of :meth:`to_jdict`; rows without ``stages`` read as none.

        Keys it does not know are ignored, so a log written by a later version
        still loads here instead of failing on its first new field.
        """
        return cls(
            ok=d["ok"],
            failing_tests=d.get("failing_tests", ()),
            failing_files=d.get("failing_files", ()),
            duration=d.get("duration", 0.0),
            stdout_tail=d.get("stdout_tail", ""),
            returncode=d.get("returncode"),
            stages=tuple(StageRun.from_jdict(s) for s in d.get("stages") or ()),
        )


#: What a row records when its validator had no fingerprint. Not ``None``: that
#: is what rows written before fingerprints existed read back as, and the
#: migration switch (``trust_unpinned``) must not adopt today's rows from an
#: unknown validator as if they were old rows from a known one (#32).
UNKNOWN_FINGERPRINT = "unknown"


@dataclass(frozen=True)
class Evaluation:
    """One row of the evaluation log — the single source of truth.

    Everything else (conflict set, known-good/known-bad closure, merge plan,
    reports) is *derived* from a sequence of these and is re-derivable.

    A row is about the commits that were actually merged, not about the ids:
    ``base_sha`` and ``heads`` (change id -> head sha) pin it to them, so a row
    written before a branch was rewritten is never mistaken for an answer about
    the rewritten branch (i2mint/mergeset#23). Rows written before pinning
    existed carry neither and read back as *unpinned*; see
    :class:`mergeset.log.EvaluationLog`. ``validator`` pins it to what was run
    on that tree, the same way (i2mint/mergeset#32): the same commits under a
    different test command are a different question.
    """

    subset: ChangeSet
    verdict: Verdict
    stage: Optional[Stage] = None
    merge: Optional[MergeOutcome] = None
    validation: Optional[ValidationOutcome] = None
    duration: float = 0.0
    at: Optional[str] = None  # ISO timestamp, filled by the log
    note: str = ""
    #: Full sha of the base the set was merged onto. ``None`` on unpinned rows.
    base_sha: Optional[str] = None
    #: Full head sha of each change in ``subset`` when it was evaluated.
    heads: Mapping[ChangeId, str] = field(default_factory=dict)
    #: Fingerprint of the validator that judged the tree (see
    #: :func:`mergeset.validation.fingerprint_of`). ``None`` on rows written
    #: before fingerprints, and on rows judged by a validator that has none.
    validator: Optional[str] = None
    #: True when this came from the log rather than from a real run. Not
    #: serialized: it is a fact about *this* lookup, not about the evaluation.
    cached: bool = False

    @property
    def ok(self) -> bool:
        """True iff the set evaluated as good."""
        return self.verdict is Verdict.PASS

    def to_jdict(self) -> dict:
        """JSON-able view; ``subset`` becomes a sorted list."""
        return {
            "subset": list(set_key(self.subset)),
            "verdict": self.verdict.value,
            "stage": self.stage.value if self.stage else None,
            "merge": self.merge.to_jdict() if self.merge else None,
            "validation": self._validation_jdict(),
            # Beside ``validation``, not inside it: releases before #17 build
            # ``ValidationOutcome(**validation)`` and would refuse the whole log
            # over one unknown key, while they ignore unknown top-level keys.
            # Beside ``merge`` for the same reason (see MergeOutcome).
            "merge_resolved_commit": (
                self.merge.resolved_commit if self.merge else None
            ),
            "validation_stages": (
                [s.to_jdict() for s in self.validation.stages]
                if self.validation
                else []
            ),
            "duration": self.duration,
            "at": self.at,
            "note": self.note,
            "base_sha": self.base_sha,
            "heads": dict(sorted(self.heads.items())),
            "validator": self.validator,
        }

    def _validation_jdict(self) -> Optional[dict]:
        if self.validation is None:
            return None
        jdict = self.validation.to_jdict()
        del jdict["stages"]  # stored beside it; see ``to_jdict``
        return jdict

    @classmethod
    def from_jdict(cls, d: Mapping[str, Any]) -> "Evaluation":
        """Inverse of :meth:`to_jdict`."""
        merge = d.get("merge")
        validation = d.get("validation")
        if validation and d.get("validation_stages"):
            validation = {**validation, "stages": d["validation_stages"]}
        return cls(
            subset=frozenset(d["subset"]),
            verdict=Verdict(d["verdict"]),
            stage=Stage(d["stage"]) if d.get("stage") else None,
            merge=(
                MergeOutcome(**merge, resolved_commit=d.get("merge_resolved_commit"))
                if merge
                else None
            ),
            validation=ValidationOutcome.from_jdict(validation) if validation else None,
            duration=d.get("duration", 0.0),
            at=d.get("at"),
            note=d.get("note", ""),
            # Absent on rows written before pinning: they read back unpinned,
            # never dropped (i2mint/mergeset#23).
            base_sha=d.get("base_sha"),
            heads=dict(d.get("heads") or {}),
            # Absent on rows written before i2mint/mergeset#32: read back as
            # judged by an unknown validator, never dropped.
            validator=d.get("validator"),
        )

    @property
    def pinned(self) -> bool:
        """True iff the row records which commits it was evaluated against."""
        return self.base_sha is not None


@runtime_checkable
class Evaluator(Protocol):
    """Callable that decides whether a change set is good.

    This is *the* expensive seam: one call is typically a merge plus a test run.
    """

    def __call__(self, subset: ChangeSet) -> Evaluation:
        """Evaluate ``subset`` and return the full record, not just a bit."""
        ...


#: A merge function: (changes to merge, in order) -> outcome + a tree to validate.
MergeFn = Callable[..., MergeOutcome]

#: A validation function: (path to a merged worktree) -> outcome.
ValidateFn = Callable[..., ValidationOutcome]


class MergesetError(Exception):
    """Base class for errors this package raises deliberately."""


class CapabilityError(MergesetError):
    """A required external capability is missing; the message says how to fix it."""
