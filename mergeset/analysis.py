"""The facade: one call that goes from a repository to a merge plan.

``analyze`` is the "simple thing made simple" entry point. It wires together the
pieces — sources, cheap pre-oracles, file-overlap decomposition, the expensive
oracle, the log, the search — with defaults that work out of the box, and every
piece stays replaceable by one keyword argument.

The order of operations is the whole point, because it is the order of *cost*:

1. free: per-change CI status (a red singleton is a conflict of size one);
2. milliseconds: pairwise ``git merge-tree`` textual conflicts;
3. milliseconds: file-overlap components — independent subproblems;
4. minutes each: the real merge-and-test oracle, only on what is left.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)

from mergeset.base import (
    Change,
    ChangeId,
    ChangeSet,
    MergesetError,
    ValidationOutcome,
    Verdict,
    set_key,
)
from mergeset.gitops import (
    changed_files,
    singleton_textual_conflicts,
    check_git_capability,
    merge_base,
    pairwise_textual_conflicts,
    resolve,
)
from mergeset.attribution import git_diff_reader, suspects as attribute_suspects
from mergeset.log import EvaluationLog
from mergeset.oracle import Resolver, git_oracle, merge_order
from mergeset.solve import (
    SearchState,
    combine_components,
    find_maximal_good_sets,
    independent_components,
)
from mergeset.sources import detect_stacks, size_weight
from mergeset.stacks import (
    close_up,
    cone_weights,
    count_closed_subsets,
    stack_roots,
    tips,
)


@dataclass
class Analysis:
    """Everything a run learned. Every field is derivable from ``log`` + git."""

    repo: str
    base: str
    base_sha: str
    changes: List[Change]
    maximal_sets: List[ChangeSet] = field(default_factory=list)
    conflicts: List[ChangeSet] = field(default_factory=list)
    textual_conflicts: List[Tuple[ChangeId, ChangeId, List[str]]] = field(
        default_factory=list
    )
    components: List[ChangeSet] = field(default_factory=list)
    files_by_change: Dict[ChangeId, List[str]] = field(default_factory=dict)
    stacks: Dict[ChangeId, ChangeId] = field(default_factory=dict)
    #: Cost of dropping each change *including its descendant cone*.
    weights: Dict[ChangeId, float] = field(default_factory=dict)
    #: Cost of the change on its own, before the cone is accounted for.
    own_weights: Dict[ChangeId, float] = field(default_factory=dict)
    #: Changes that will not even merge onto base alone -> conflicting files.
    singleton_conflicts: Dict[ChangeId, List[str]] = field(default_factory=dict)
    log: Optional[EvaluationLog] = None
    searches: List[SearchState] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def by_id(self) -> Dict[ChangeId, Change]:
        """Changes keyed by id."""
        return {c.id: c for c in self.changes}

    @property
    def evaluations(self) -> int:
        """How many expensive evaluations this run actually spent."""
        return sum(s.evaluations for s in self.searches)

    @property
    def exhausted(self) -> bool:
        """True iff every component's search finished rather than hit a budget."""
        return all(s.exhausted for s in self.searches) if self.searches else False

    def merge_plan(self) -> List[dict]:
        """One entry per maximal set: what to merge, in what order, what it drops.

        This is the deliverable — "merge these, in this order, and you lose these".
        """
        all_ids = frozenset(c.id for c in self.changes)
        by_id = self.by_id
        plans = []
        for rank, subset in enumerate(self.maximal_sets, start=1):
            dropped = all_ids - subset
            merge_these = tips(subset, self.stacks)
            plans.append(
                {
                    "rank": rank,
                    "changes": list(merge_order(subset, by_id)),
                    # Merging a stack's tip brings its ancestors along, so these
                    # are the merges you actually perform.
                    "merge": list(merge_order(merge_these, by_id)),
                    "dropped": list(set_key(dropped)),
                    "dropped_weight": round(
                        sum(self.weights.get(i, 1.0) for i in dropped), 3
                    ),
                    "kept_weight": round(
                        sum(self.weights.get(i, 1.0) for i in subset), 3
                    ),
                    "size": len(subset),
                }
            )
        return sorted(plans, key=lambda p: (p["dropped_weight"], -p["size"]))


def analyze(
    repo: str,
    changes: Sequence[Change],
    *,
    base: Optional[str] = None,
    validate: Optional[Callable[[str], ValidationOutcome]] = None,
    resolver: Optional[Resolver] = None,
    log: Optional[EvaluationLog] = None,
    log_path: Optional[str] = None,
    weight: Optional[Callable[[Change], float]] = None,
    pairwise_preoracle: bool = True,
    decompose: bool = True,
    component_local: Optional[bool] = None,
    use_ci_status: bool = True,
    check_base: bool = True,
    max_evaluations: Optional[int] = None,
    max_seconds: Optional[float] = None,
    max_sets: Optional[int] = None,
    worktree_root: Optional[str] = None,
    reuse_worktree: Optional[str] = None,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> Analysis:
    """Find the maximal sets of ``changes`` that merge and validate on ``base``.

    Args:
        repo: Path to the git repository.
        changes: Candidate changes (see :mod:`mergeset.sources`).
        base: What to merge onto. Default: the merge base of every change's own
            base, which is the only choice that is fair to all of them.
        validate: ``worktree -> ValidationOutcome``; default is a fail-fast
            pytest run. Pass ``merge_only_validation()`` for a free first pass.
        resolver: Optional AI-assisted conflict resolver (results are flagged).
        log / log_path: The evaluation log — the single source of truth. Reusing
            an existing one makes a re-run nearly free.
        weight: ``Change -> cost of dropping it``; default is size-based.
        pairwise_preoracle: Use ``git merge-tree`` to find textual conflicts for
            free before spending any evaluation.
        decompose: Use file-overlap components to find conflicts cheaply. The
            components are always searched first, because a conflict found
            inside a small component is a conflict found for a fraction of the
            price; whether their answers are then *trusted* to combine is
            ``component_local``.
        component_local: Assert that the validator cannot see across
            components — i.e. that two changes touching disjoint files can never
            fail together. True for a merge-only or per-file validator; **false
            for any whole-repo test run**, which can fail on generated
            artifacts, barrel exports, snapshots, type checks or project-wide
            lint that no changed-file overlap predicts. When false (the
            default), the combined result is verified by a global search seeded
            with every conflict the components found. ``None`` (the default)
            asks the validator: one may set ``validate.component_local = True``
            to declare it, as :func:`~mergeset.validation.merge_only_validation`
            does.
        check_base: Evaluate the base commit on its own before anything else, so
            a broken base or a misconfigured validator is a refusal rather than
            15 confident failures.
        use_ci_status: Treat a change whose own CI is red as a size-1 conflict.
        max_evaluations, max_seconds, max_sets: Budgets; partial results are
            always returned.
        reuse_worktree: Reuse one worktree for every evaluation instead of a
            fresh one, so an expensive setup step (``npm install``, a build
            cache) is paid once rather than per evaluation. Pair it with
            :func:`mergeset.validation.staged_validation`.
        on_event: ``(event, payload)`` progress callback.

    Returns:
        An :class:`Analysis`.
    """
    check_git_capability()
    changes = list(changes)
    emit = on_event or (lambda name, payload: None)
    if not changes:
        raise ValueError("No candidate changes were given; nothing to analyze.")

    base = base or _common_base(repo, changes)
    base_sha = resolve(repo, base)
    if log is None:
        log = EvaluationLog(
            log_path or os.path.join(repo, ".mergeset", "evaluations.jsonl")
        )

    # A validator may declare that it cannot see across components (the
    # merge-only one does); otherwise assume it can, which is the safe default.
    if component_local is None:
        component_local = bool(getattr(validate, "component_local", False))

    weight = weight or (lambda c: size_weight(repo, c))
    own_weights = {
        c.id: (c.weight if c.weight is not None else weight(c)) for c in changes
    }

    stacks = detect_stacks(changes)
    # Dropping a change drops everything stacked on it, so that is what dropping
    # it costs. Weighting changes independently lets the hitting set discard a
    # whole stack while believing it discarded one small PR.
    weights = cone_weights(own_weights, stacks)

    analysis = Analysis(
        repo=repo,
        base=base,
        base_sha=base_sha,
        changes=changes,
        weights=weights,
        own_weights=own_weights,
        log=log,
        stacks=stacks,
    )
    if stacks:
        ids = [c.id for c in changes]
        analysis.notes.append(
            f"{len(stacks)} of {len(changes)} changes are stacked on another "
            f"candidate. Only downward-closed sets are considered, which reduces "
            f"the search space from {2 ** len(ids)} subsets to "
            f"{count_closed_subsets(stacks, ids)} valid ones."
        )
    for child, parent in stacks.items():
        analysis.notes.append(
            f"{child} is stacked on {parent}: it already contains it, so a set "
            f"holding {child} must hold {parent}, and dropping {parent} drops "
            f"{child} too."
        )

    analysis.files_by_change = {
        c.id: changed_files(repo, base_sha, c.head) for c in changes
    }

    known_conflicts: List[ChangeSet] = []
    if use_ci_status:
        for c in changes:
            # A forge's CI/mergeable verdict is about the PR's OWN base branch.
            # When that is not the base we are merging onto, the verdict says
            # nothing about this analysis -- a PR can be green and "MERGEABLE"
            # on GitHub and still refuse to merge onto main, because its base
            # branch moved on without it. Trust the signal only when the bases
            # agree, and say so when they do not.
            own_base = c.meta.get("base_ref")
            same_base = own_base is None or base.endswith(own_base)
            if c.meta.get("ci") == "failure" and same_base:
                known_conflicts.append(frozenset({c.id}))
                analysis.notes.append(
                    f"{c.id} is excluded for free: its own CI is red against "
                    f"`{own_base}`, which is the base we are merging onto."
                )
            elif c.meta.get("ci") and not same_base:
                analysis.notes.append(
                    f"{c.id}'s CI status (`{c.meta['ci']}`) is against `{own_base}`, "
                    f"not `{base}`, so it is ignored as a pre-oracle. Its "
                    "mergeability here is decided by actually merging it."
                )

    # The cheapest oracle of all: does each change even merge onto base alone?
    heads_by_id = {c.id: c.head for c in changes}
    if pairwise_preoracle:
        for change_id, files in singleton_textual_conflicts(repo, base_sha, heads_by_id):
            known_conflicts.append(frozenset({change_id}))
            analysis.singleton_conflicts[change_id] = files
            analysis.notes.append(
                f"{change_id} does not merge onto the base at all "
                f"({len(files)} conflicting files). Excluded before any test ran."
            )

    if pairwise_preoracle:
        viable = {
            cid: head
            for cid, head in heads_by_id.items()
            if cid not in analysis.singleton_conflicts
        }
        analysis.textual_conflicts = list(
            pairwise_textual_conflicts(repo, base_sha, viable)
        )
        for a, b, files in analysis.textual_conflicts:
            known_conflicts.append(frozenset({a, b}))
            emit("textual_conflict", {"pair": (a, b), "files": files})

    ids = [c.id for c in changes]
    if decompose:
        analysis.components = independent_components(
            ids, lambda cid: analysis.files_by_change.get(cid, ())
        )
    else:
        analysis.components = [frozenset(ids)]

    evaluate = log.caching(
        git_oracle(
            repo,
            base_sha,
            changes,
            validate=validate,
            resolver=resolver,
            depends_on=analysis.stacks,
            reuse_worktree=reuse_worktree,
            worktree_root=worktree_root,
            on_event=on_event,
        )
    )

    if check_base:
        # One evaluation of the empty set. If the base does not validate, every
        # subsequent failure is meaningless and "nothing can be merged" would be
        # reported as a finding rather than as the misconfiguration it is.
        baseline = evaluate(frozenset())
        if baseline.verdict is not Verdict.PASS:
            detail = baseline.note or ""
            if baseline.validation is not None:
                detail = "; ".join(baseline.validation.failing_tests[:5]) or detail
            raise MergesetError(
                f"The base ({base} @ {base_sha[:8]}) does not pass validation on "
                f"its own: {detail}\n\n"
                "Every result would be meaningless, so nothing was evaluated. "
                "Either the base is genuinely broken, or the validation command "
                "is wrong for this repository. Check it by hand, then re-run "
                "(pass check_base=False to proceed anyway)."
            )

    diff_of = git_diff_reader(repo, base_sha, heads_by_id)

    def suspects_from_failure(result, subset: ChangeSet) -> ChangeSet:
        """Which changes in ``subset`` the failure output points at."""
        if result.validation is None:
            return frozenset()
        return attribute_suspects(
            result.validation,
            files_by_change=analysis.files_by_change,
            within=subset,
            diff_of=diff_of,
        )

    per_component: List[List[ChangeSet]] = []
    for component in analysis.components:
        component_conflicts = [c for c in known_conflicts if c <= component]
        emit("component", {"changes": set_key(component)})
        state = find_maximal_good_sets(
            component,
            evaluate,
            known_conflicts=component_conflicts,
            depends_on=analysis.stacks,
            weight=lambda cid: weights.get(cid, 1.0),
            max_evaluations=max_evaluations,
            max_seconds=max_seconds,
            max_sets=max_sets,
            suspects=suspects_from_failure,
            on_event=on_event,
        )
        analysis.searches.append(state)
        analysis.conflicts.extend(state.conflicts)
        per_component.append(state.maximal_good_sets or [frozenset()])

    combined = combine_components(per_component)
    if component_local or len(analysis.components) <= 1:
        analysis.maximal_sets = combined
    else:
        # Decomposition is sound for *textual* conflicts and unsound for
        # anything a whole-repo run can see: a drift test in one component can
        # read generated artifacts derived from sources another component edits,
        # with no changed file in common. So the components buy cheap conflicts,
        # and then one global search -- seeded with every one of them, so it
        # starts almost finished -- decides the answer.
        analysis.notes.append(
            f"{len(analysis.components)} file-overlap components were searched "
            "first to find conflicts cheaply, then verified globally: a whole-repo "
            "validator can fail on changes that share no file, so component "
            "results are not assumed to combine freely "
            "(pass component_local=True if your validator cannot see across them)."
        )
        global_state = find_maximal_good_sets(
            [c.id for c in changes],
            evaluate,
            known_conflicts=analysis.conflicts,
            depends_on=analysis.stacks,
            weight=lambda cid: weights.get(cid, 1.0),
            max_evaluations=max_evaluations,
            max_seconds=max_seconds,
            max_sets=max_sets,
            suspects=suspects_from_failure,
            on_event=on_event,
        )
        analysis.searches.append(global_state)
        analysis.conflicts = _dedupe_conflicts(
            analysis.conflicts + global_state.conflicts
        )
        analysis.maximal_sets = global_state.maximal_good_sets or combined

    for state in analysis.searches:
        if state.error:
            analysis.notes.append(
                f"ABORTED: {state.error}. The sets below are whatever had been "
                "established before that point; they are not an answer."
            )
    violations = log.monotonicity_violations()
    for good, bad in violations:
        analysis.notes.append(
            f"MONOTONICITY VIOLATION: {set_key(bad)} failed but {set_key(good)} "
            "passed, though it contains it. Suspect a flaky test, or a change "
            "that fixes another. Results below are not fully trustworthy."
        )
    return analysis


def _common_base(repo: str, changes: Sequence[Change]) -> str:
    """The commit every change can fairly be measured against.

    When all candidates already share a base, that is it. When they do not
    (stacked PRs, PRs opened against a non-default branch), fall back to the
    merge base of all of them — and the caller is told, because "which base"
    silently differing is the classic way this analysis becomes meaningless.
    """
    bases = {c.base for c in changes}
    if len(bases) == 1:
        return next(iter(bases))
    current = resolve(repo, sorted(bases)[0])
    for other in sorted(bases)[1:]:
        current = merge_base(repo, current, resolve(repo, other))
    return current


def _dedupe_conflicts(conflicts: Sequence[ChangeSet]) -> List[ChangeSet]:
    """Keep only the minimal conflicts; a superset of a conflict says nothing new."""
    unique = {frozenset(c) for c in conflicts if c}
    return sorted(
        (c for c in unique if not any(other < c for other in unique)),
        key=lambda c: (len(c), set_key(c)),
    )
