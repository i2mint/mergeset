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
    """Result of merging a change set onto its base."""

    ok: bool
    conflicting_files: Sequence[str] = ()
    assisted: bool = False  # resolved by an AI assist rather than cleanly
    assist_diff: Optional[str] = None
    order: Sequence[ChangeId] = ()
    detail: str = ""

    def to_jdict(self) -> dict:
        """JSON-able view."""
        return {
            "ok": self.ok,
            "conflicting_files": list(self.conflicting_files),
            "assisted": self.assisted,
            "assist_diff": self.assist_diff,
            "order": list(self.order),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ValidationOutcome:
    """Result of validating a merged tree."""

    ok: bool
    failing_tests: Sequence[str] = ()
    failing_files: Sequence[str] = ()
    duration: float = 0.0
    stdout_tail: str = ""
    returncode: Optional[int] = None

    def to_jdict(self) -> dict:
        """JSON-able view."""
        return {
            "ok": self.ok,
            "failing_tests": list(self.failing_tests),
            "failing_files": list(self.failing_files),
            "duration": self.duration,
            "stdout_tail": self.stdout_tail,
            "returncode": self.returncode,
        }


@dataclass(frozen=True)
class Evaluation:
    """One row of the evaluation log — the single source of truth.

    Everything else (conflict set, known-good/known-bad closure, merge plan,
    reports) is *derived* from a sequence of these and is re-derivable.
    """

    subset: ChangeSet
    verdict: Verdict
    stage: Optional[Stage] = None
    merge: Optional[MergeOutcome] = None
    validation: Optional[ValidationOutcome] = None
    duration: float = 0.0
    at: Optional[str] = None  # ISO timestamp, filled by the log
    note: str = ""
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
            "validation": self.validation.to_jdict() if self.validation else None,
            "duration": self.duration,
            "at": self.at,
            "note": self.note,
        }

    @classmethod
    def from_jdict(cls, d: Mapping[str, Any]) -> "Evaluation":
        """Inverse of :meth:`to_jdict`."""
        merge = d.get("merge")
        validation = d.get("validation")
        return cls(
            subset=frozenset(d["subset"]),
            verdict=Verdict(d["verdict"]),
            stage=Stage(d["stage"]) if d.get("stage") else None,
            merge=MergeOutcome(**merge) if merge else None,
            validation=ValidationOutcome(**validation) if validation else None,
            duration=d.get("duration", 0.0),
            at=d.get("at"),
            note=d.get("note", ""),
        )


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
