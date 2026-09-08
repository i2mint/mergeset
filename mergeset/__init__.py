"""Which of these branches can be merged together?

Given a base commit and *n* candidate changes (branches, PRs, commits),
``mergeset`` finds the **maximal sets** that merge cleanly and still pass
validation — and the minimal **conflicts** that stop the rest.

The simple case is one call::

    from mergeset import analyze, branch_changes, markdown_report

    changes = list(branch_changes('.', ['feature-a', 'feature-b'], base='main'))
    analysis = analyze('.', changes)
    print(markdown_report(analysis))

Everything expensive is cached in an append-only JSONL log, so a second run
costs nothing for sets already decided, and the cheap oracles (per-change CI
status, ``git merge-tree`` textual conflicts, file-overlap decomposition) run
first so that most answers never cost a test run at all.

Every piece is one keyword argument away from being replaced: where changes come
from (``mergeset.sources``), how a set is merged and validated
(``mergeset.oracle``, ``mergeset.validation``), how the search spends its budget
(``mergeset.solve``), and how results are rendered (``mergeset.report``).
"""

from mergeset.base import (
    CapabilityError,
    Change,
    ChangeSet,
    Evaluation,
    MergeOutcome,
    MergesetError,
    ValidationOutcome,
    Verdict,
    change_set,
    set_key,
)
from mergeset.log import EvaluationLog, JsonlLines, MemoryLines
from mergeset.solve import (
    combine_components,
    find_maximal_good_sets,
    independent_components,
    minimal_hitting_sets,
    quickxplain,
)
from mergeset.gitops import (
    changed_files,
    create_integration_branch,
    merge_sequence,
    merged_worktree,
    pairwise_textual_conflicts,
    persistent_worktree,
    singleton_textual_conflicts,
    textual_conflict,
)
from mergeset.stacks import (
    ancestors,
    close_down,
    close_up,
    cone_weights,
    count_closed_subsets,
    descendants,
    largest_closed_subset,
    tips,
)
from mergeset.sources import (
    branch_changes,
    commit_changes,
    detect_stacks,
    fetch_pull_requests,
    local_branch_names,
    pr_changes,
)
from mergeset.validation import (
    ValidationStage,
    act_validation,
    callable_validation,
    command_validation,
    file_fingerprint,
    flake_tolerant,
    js_validation,
    merge_only_validation,
    pytest_validation,
    staged_validation,
)
from mergeset.oracle import claude_code_resolver, git_oracle, merge_order
from mergeset.analysis import Analysis, analyze
from mergeset.report import html_report, markdown_report

__all__ = [
    "analyze", "Analysis",
    "Change", "ChangeSet", "Evaluation", "Verdict", "MergeOutcome", "ValidationOutcome",
    "change_set", "set_key",
    "EvaluationLog", "JsonlLines", "MemoryLines",
    "branch_changes", "commit_changes", "pr_changes", "fetch_pull_requests",
    "local_branch_names", "detect_stacks",
    "pytest_validation", "command_validation", "act_validation",
    "callable_validation", "merge_only_validation", "flake_tolerant",
    "staged_validation", "ValidationStage", "js_validation", "file_fingerprint",
    "tips", "close_down", "close_up", "largest_closed_subset", "cone_weights",
    "ancestors", "descendants", "count_closed_subsets",
    "git_oracle", "merge_order", "claude_code_resolver",
    "find_maximal_good_sets", "quickxplain", "minimal_hitting_sets",
    "independent_components", "combine_components",
    "textual_conflict", "pairwise_textual_conflicts", "singleton_textual_conflicts",
    "changed_files", "merge_sequence", "merged_worktree", "persistent_worktree",
    "create_integration_branch",
    "markdown_report", "html_report",
    "MergesetError", "CapabilityError",
]

__version__ = "0.0.1"
