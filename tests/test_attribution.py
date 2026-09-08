"""Attribution, against the real vitest output the TEST workstream captured."""

import os

import pytest

from mergeset.attribution import identifiers_in, paths_in, suspects
from mergeset.base import ValidationOutcome

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "notes", "fixtures")


def fixture(name):
    path = os.path.join(FIXTURES, name)
    if not os.path.exists(path):
        pytest.skip(f"fixture {name} not present")
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def outcome(text, **kw):
    return ValidationOutcome(ok=False, stdout_tail=text, **kw)


def test_paths_ignores_dependency_directories():
    text = " at Module.getEnumValues node_modules/.pnpm/zod@4.4.3/core/util.js:15:34"
    assert paths_in(text) == []


def test_paths_finds_the_source_frame_not_only_the_test():
    text = (
        " FAIL  tests/unit/commands.test.ts [ tests/unit/commands.test.ts ]\n"
        " ❯ packages/app/store/commands/schemas.ts:89:4\n"
    )
    assert paths_in(text) == [
        "tests/unit/commands.test.ts",
        "packages/app/store/commands/schemas.ts",
    ]


def test_identifiers_picks_up_camel_and_pascal_case():
    found = identifiers_in('+ "pointColorHopSeeds": {"$ref": "TraversalDirectionType"}')
    assert "pointColorHopSeeds" in found and "TraversalDirectionType" in found


def test_collection_failure_attributes_via_the_source_file(): 
    """#577/#587: four suites fail to load, so there are no test ids at all.

    The only actionable path is a *source* file, added by #577.
    """
    text = fixture("vitest-577-587-import-crash.txt")
    files = {
        "pr577": ["packages/app/features/project-builder/store/commands/schemas.ts"],
        "pr587": ["packages/app/stories/index.ts"],
        "pr630": ["docs/readme.md"],
    }
    found = suspects(outcome(text), files_by_change=files, within=files)
    assert "pr577" in found
    assert "pr630" not in found


def test_drift_failure_needs_symbols_because_files_point_at_the_wrong_change():
    """#579/#631: the failing test is in a file #631 added; #579 is the culprit.

    #579 shares no file with the failing test, so file-level attribution alone
    accuses the innocent change. Matching the identifiers in the assertion diff
    against each candidate's *added* lines is what gets it right.
    """
    text = fixture("vitest-579-631-drift.txt")
    files = {
        "pr579": ["packages/config/point-color.ts"],   # touches no test file
        "pr631": ["tests/unit/params-ssot.test.ts", "ai/schemas/config.schema.json"],
        "pr630": ["docs/readme.md"],                   # uninvolved bystander
        "pr632": ["packages/ui/toolbar.tsx"],          # uninvolved bystander
    }
    diffs = {
        "pr579": (
            "+++ b/packages/config/point-color.ts\n"
            "+  pointColorHopDirection?: TraversalDirectionType\n"
            "+  pointColorHopSeeds?: number[]\n"
        ),
        "pr631": (
            "+++ b/tests/unit/params-ssot.test.ts\n"
            "+ it('matches the TypeScript sources', () => {})\n"
        ),
        "pr630": "+++ b/docs/readme.md\n+ a docs line\n",
        "pr632": "+++ b/packages/ui/toolbar.tsx\n+ const Toolbar = () => null\n",
    }

    by_file_only = suspects(
        outcome(text, failing_tests=["tests/unit/params-ssot.test.ts > x"]),
        files_by_change=files, within=files,
    )
    assert by_file_only == frozenset({"pr631"}), "file-level alone accuses the wrong one"

    with_symbols = suspects(
        outcome(text, failing_tests=["tests/unit/params-ssot.test.ts > x"]),
        files_by_change=files, within=files, diff_of=diffs.get,
    )
    assert "pr579" in with_symbols, "symbol matching must find the real culprit"
    # The union of both signals is exactly the real conflict, and it excludes
    # the bystanders -- which is what makes it worth a targeted shrink.
    assert with_symbols == frozenset({"pr579", "pr631"})


def test_a_symbol_merely_mentioned_is_not_evidence():
    """Only *added* lines count: using a symbol is not introducing it."""
    files = {"a": ["a.ts"], "b": ["b.ts"]}
    diffs = {
        "a": "+++ b/a.ts\n+const x = newThingHere()\n",
        "b": "+++ b/b.ts\n-const y = newThingHere()\n context newThingHere\n",
    }
    found = suspects(
        outcome("TypeError: newThingHere is not defined"),
        files_by_change=files, within=files, diff_of=diffs.get,
    )
    assert found == frozenset({"a"})


def test_no_evidence_yields_no_hint_rather_than_a_guess():
    files = {"a": ["a.ts"], "b": ["b.ts"]}
    assert suspects(outcome("something went wrong"), files_by_change=files, within=files) == frozenset()


def test_implicating_everything_is_the_same_as_implicating_nothing():
    """A hint that names every candidate has saved no evaluations, so say so."""
    files = {"a": ["shared.ts"], "b": ["shared.ts"]}
    found = suspects(
        outcome("FAIL src/shared.ts"), files_by_change=files, within=files
    )
    assert found == frozenset(), "a hint naming the whole set saves nothing"
