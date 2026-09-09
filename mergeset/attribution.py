"""From a failure to the changes that probably caused it.

When a set fails, the expensive information has already been paid for: the
runner said *what* failed. Turning that into "which of these changes did it"
saves the conflict-shrinking step several oracle calls, and on real failures it
lands directly on the culprit.

Three signals, in increasing order of how much they prove:

1. **Paths in the failure block.** Every path a failure mentions, not only the
   failing test's own file — a stack trace's actionable frame is usually a
   *source* file, and when a suite fails to load there are no test ids at all.
2. **The changes that touched those paths.** File-level attribution, the obvious
   move, and by itself frequently wrong: a drift test added by one change fails
   because of what a *different* change did to the sources it derives from.
3. **Identifiers named in the failure.** When the output quotes symbols — an
   assertion diff, an undefined name, a missing export — matching those against
   each candidate's diff finds the change that introduced them even when it
   shares no file with the failing test. This is the only signal that gets that
   drift case right.

Everything here is a *hint*. A wrong hint costs the search one wasted check and
then it falls back to unguided shrinking; it never decides a verdict.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from mergeset.base import ChangeId, ChangeSet, ValidationOutcome

#: A path-looking token: at least one directory separator and a known extension.
_PATH = re.compile(
    r"[\w./@-]*[\w@-]+/[\w./@-]+\.(?:ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|rb|json|yaml|yml)"
)

#: An identifier worth matching against a diff: camelCase or PascalCase, long
#: enough not to collide with ordinary English.
_IDENTIFIER = re.compile(r"\b(?:[a-z]+[A-Z]|[A-Z][a-z]+[A-Z])[A-Za-z0-9]{4,}\b")

#: Paths inside a dependency directory say nothing about our changes.
_VENDOR = ("node_modules/", "site-packages/", "vendor/", ".venv/", "dist/", "build/")


def paths_in(text: str) -> List[str]:
    """Every source-looking path mentioned, vendor directories excluded.

    >>> paths_in('FAIL tests/unit/a.test.ts [ tests/unit/a.test.ts ]')
    ['tests/unit/a.test.ts']
    >>> paths_in(' at Module.x node_modules/zod/util.js:15 then src/schemas.ts:89:4')
    ['src/schemas.ts']
    """
    found = []
    for match in _PATH.findall(text):
        if any(v in match for v in _VENDOR):
            continue
        if match not in found:
            found.append(match)
    return found


def identifiers_in(text: str) -> List[str]:
    """Camel/Pascal-case identifiers named in the failure output.

    >>> identifiers_in('+ "pointColorSeeds": { "$ref": "AxisDirectionType" }')
    ['pointColorSeeds', 'AxisDirectionType']
    """
    return list(dict.fromkeys(_IDENTIFIER.findall(text)))


def failure_text(outcome: ValidationOutcome) -> str:
    """Everything a validation outcome said, as one blob to mine."""
    return "\n".join(
        [*outcome.failing_tests, *outcome.failing_files, outcome.stdout_tail or ""]
    )


def suspects(
    outcome: ValidationOutcome,
    *,
    files_by_change: Mapping[ChangeId, Sequence[str]],
    within: Iterable[ChangeId],
    diff_of: Optional[Callable[[ChangeId], str]] = None,
) -> ChangeSet:
    """Changes the failure points at, or an empty set when it points nowhere.

    Args:
        outcome: The failed validation, with whatever the runner printed.
        files_by_change: Which files each change touched.
        within: Only these changes are candidates (the set being evaluated).
        diff_of: ``change id -> its diff text``. Optional but valuable: it is
            what enables identifier matching, the only signal that attributes a
            failure to a change sharing no file with the failing test.

    Returns:
        A strict, non-empty subset of ``within``, or ``frozenset()`` when the
        evidence is absent, useless, or implicates everything (in which case it
        has told us nothing and blind shrinking is the honest fallback).

    >>> out = ValidationOutcome(ok=False, failing_tests=['tests/a.test.ts::x'])
    >>> set(suspects(out, files_by_change={'p1': ['tests/a.test.ts'], 'p2': ['b.ts']},
    ...              within=['p1', 'p2']))
    {'p1'}
    """
    within = frozenset(within)
    if not within:
        return frozenset()
    text = failure_text(outcome)
    if not text.strip():
        return frozenset()

    by_path = _touching(paths_in(text), files_by_change, within)
    by_symbol = (
        _naming(identifiers_in(text), diff_of, within) if diff_of else frozenset()
    )

    # A symbol match is the stronger evidence -- it survives the case where the
    # failing test belongs to an innocent change -- so when both fire, take the
    # union rather than the intersection: dropping either risks losing the real
    # culprit, and the cost of one extra suspect is one extra check.
    found = by_path | by_symbol
    if not found or found == within:
        return frozenset()
    return found


def _touching(
    paths: Sequence[str],
    files_by_change: Mapping[ChangeId, Sequence[str]],
    within: ChangeSet,
) -> ChangeSet:
    """Changes that touched any of ``paths`` (suffix match, so prefixes vary freely)."""
    hits: Set[ChangeId] = set()
    for change_id in within:
        touched = files_by_change.get(change_id) or ()
        for path in paths:
            if any(
                f == path or f.endswith("/" + path) or path.endswith("/" + f)
                for f in touched
            ):
                hits.add(change_id)
                break
    return frozenset(hits)


def _naming(
    identifiers: Sequence[str],
    diff_of: Callable[[ChangeId], str],
    within: ChangeSet,
) -> ChangeSet:
    """Changes whose diff introduces an identifier the failure named.

    Only *added* lines count. A change that merely mentions a symbol it did not
    introduce is not the reason the symbol is suddenly a problem.
    """
    if not identifiers:
        return frozenset()
    wanted = set(identifiers)
    hits: Set[ChangeId] = set()
    for change_id in within:
        try:
            diff = diff_of(change_id) or ""
        except Exception:  # a diff we cannot read is not evidence either way
            continue
        added = "\n".join(
            line
            for line in diff.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        if any(symbol in added for symbol in wanted):
            hits.add(change_id)
    return frozenset(hits)


def git_diff_reader(repo: str, base: str, heads: Mapping[ChangeId, str]):
    """A ``diff_of`` for :func:`suspects`, reading (and caching) real git diffs."""
    from mergeset.gitops import git

    cache: Dict[ChangeId, str] = {}

    def diff_of(change_id: ChangeId) -> str:
        if change_id not in cache:
            head = heads.get(change_id)
            cache[change_id] = (
                git(repo, "diff", f"{base}...{head}").stdout if head else ""
            )
        return cache[change_id]

    return diff_of
