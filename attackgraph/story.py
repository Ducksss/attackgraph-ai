"""Plain-language view of one finding for the judge-facing walkthrough.

Everything here is derived from engine objects; nothing is inferred. The
strings include node labels, which are untrusted display text, so callers
must escape them before rendering.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import RULE_LAMBDA, TRUE, Candidate, Finding, PotentialFinding
from .compare import Comparison, FindingDelta
from .snapshot import Snapshot

KIND_NAMES = {"principal": "Entry point", "role": "IAM role", "lambda": "Lambda function", "s3_object": "S3 object"}

# Rule B prerequisites grouped by the visual hop they belong to.
_TO_WORKLOAD = {"iam_pass_role_to_lambda", "lambda_create_function", "lambda_invoke_function", "controls_workload_code"}


@dataclass(frozen=True)
class Condition:
    text: str
    state: str
    key: str
    change: str | None  # "false → true" when the fact differs between the snapshots
    assumption: bool
    fact_id: str | None
    pointers: tuple[str, ...]


@dataclass(frozen=True)
class PathNode:
    id: str
    kind: str
    label: str
    protected: str | None


@dataclass(frozen=True)
class Hop:
    text: str
    changed: bool
    fact_ids: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class Step:
    candidate: Candidate
    title: str
    conditions: tuple[Condition, ...]
    baseline_state: str | None  # the same candidate in the baseline; None when never evaluated there
    baseline_blockers: tuple[str, ...]


@dataclass(frozen=True)
class Story:
    delta: FindingDelta
    headline: str
    nodes: tuple[PathNode, ...]
    hops: tuple[Hop, ...]
    steps: tuple[Step, ...]
    changes: tuple[Condition, ...]

    @property
    def conditions(self) -> tuple[Condition, ...]:
        return tuple(c for step in self.steps for c in step.conditions)


def label(snapshot: Snapshot, node_id: str | None) -> str:
    if node_id is None:
        return ""
    node = snapshot.nodes.get(node_id)
    return node.label if node else node_id


def condition_text(key: str, candidate: Candidate, snapshot: Snapshot) -> str:
    subject, target, via = (label(snapshot, n) for n in (candidate.subject, candidate.target, candidate.via))
    return {
        "iam_pass_role_to_lambda": f"{subject} can pass {target} to Lambda",
        "lambda_create_function": f"{subject} can create {via}",
        "lambda_invoke_function": f"{subject} can invoke {via}",
        "controls_workload_code": f"{subject} controls the code {via} runs",
        "role_trusts_lambda_service": f"{target} trusts the Lambda service",
        "same_account": "Everything is in one AWS account",
        "policy_controls_resolved": "No unresolved policy restrictions apply",
        "s3_get_object": f"{subject} can read {target}",
    }[key]


def _verb(impact: str) -> str:
    return "run code as" if impact == "privileged_role_use" else "read"


def headline(delta: FindingDelta, snapshot: Snapshot) -> str:
    entry, target, verb = label(snapshot, delta.entry), label(snapshot, delta.target), _verb(delta.impact)
    return {
        "added": f"{entry} can now {verb} {target}",
        "removed": f"{entry} can no longer {verb} {target}",
        "unchanged": f"{entry} can still {verb} {target}",
    }.get(delta.status, f"Unresolved: can {entry} {verb} {target}?")


def build_story(comparison: Comparison, delta: FindingDelta) -> Story:
    record = delta.current
    analysis = comparison.proposal if delta.proposal is not None else comparison.baseline
    snapshot = analysis.snapshot
    witness = record.witness if isinstance(record, Finding) else record.possible_witness
    changed_ids = comparison.changed_fact_ids

    def condition(candidate: Candidate, p) -> Condition:
        change = comparison.fact_change(p.fact_id) if p.fact_id in changed_ids else None
        return Condition(
            text=condition_text(p.key, candidate, snapshot),
            state=p.state,
            key=p.key,
            change=f"{change.before} → {change.after}" if change else None,
            assumption=p.assumption,
            fact_id=p.fact_id,
            pointers=p.pointers,
        )

    nodes: list[PathNode] = []
    hops: list[Hop] = []
    steps: list[Step] = []

    def add_node(node_id: str) -> None:
        node = snapshot.nodes[node_id]
        target = snapshot.protected_targets.get(node_id)
        nodes.append(PathNode(node_id, node.kind, node.label, target.classification if target else None))

    for candidate in witness:
        if not nodes:
            add_node(candidate.subject)
        facts = {p.key: p.fact_id for p in candidate.prerequisites if p.fact_id}
        if candidate.rule == RULE_LAMBDA:
            first = tuple(f for k, f in facts.items() if k in _TO_WORKLOAD)
            second = tuple(f for k, f in facts.items() if k not in _TO_WORKLOAD)
            hops.append(
                Hop(
                    f"can pass {label(snapshot, candidate.target)} to",
                    bool(set(first) & changed_ids),
                    first,
                    candidate.state,
                )
            )
            add_node(candidate.via)
            hops.append(Hop("runs as", bool(set(second) & changed_ids), second, candidate.state))
            title = (
                f"{label(snapshot, candidate.subject)} can run code as {label(snapshot, candidate.target)} "
                f"through {label(snapshot, candidate.via)}"
            )
        else:
            hops.append(Hop("can read", bool(set(facts.values()) & changed_ids), tuple(facts.values()), candidate.state))
            title = f"{label(snapshot, candidate.subject)} can read {label(snapshot, candidate.target)}"
        add_node(candidate.target)

        conditions = [condition(candidate, p) for p in candidate.prerequisites]
        conditions.sort(key=lambda c: c.change is None)  # changed conditions first, stable otherwise
        before = comparison.baseline.candidates.get(candidate.id)
        blockers = tuple(
            p.fact_id or p.key for p in (before.prerequisites if before else ()) if p.state != TRUE
        )
        steps.append(Step(candidate, title, tuple(conditions), before.state if before else None, blockers))

    changes = tuple(c for step in steps for c in step.conditions if c.change is not None)
    return Story(delta, headline(delta, snapshot), tuple(nodes), tuple(hops), tuple(steps), changes)


def involves_pass_role(story: Story) -> bool:
    return any(step.candidate.rule == RULE_LAMBDA for step in story.steps)


def is_potential(delta: FindingDelta) -> bool:
    return isinstance(delta.current, PotentialFinding)


def expected_text(check, snapshot: Snapshot) -> str:
    verb = "reads" if check.relationship == "object_read" else "can use"
    return f"{label(snapshot, check.principal)} {verb} {label(snapshot, check.target)}"


def summary(story: Story, fix=None) -> list[str]:
    """Deterministic plain-language sentences; shown when no AI explanation is on screen."""
    delta = story.delta
    sentences = [story.headline + "."] if delta.status != "inconclusive" else []
    changes = [f"{c.text} ({c.change.replace(' → ', ' to ')})" for c in story.changes]
    if delta.status == "added":
        if changes:
            lead = "The proposal changes one condition" if len(changes) == 1 else f"The proposal changes {len(changes)} conditions"
            sentences.append(f"{lead}: {'; '.join(changes)}.")
        sentences.append(f"With it, all {len(story.conditions)} conditions on this route hold.")
    elif delta.status == "removed":
        if changes:
            sentences.append(f"The second snapshot changes: {'; '.join(changes)}.")
    elif delta.status == "unchanged":
        sentences.append("The route exists in both snapshots.")
    else:
        unknown = [c.text for c in story.conditions if c.state == "unknown"]
        entry, target = story.nodes[0].label, story.nodes[-1].label
        sentences.append(
            f"It is unresolved whether {entry} can reach {target}: "
            + ("; ".join(unknown) or "a condition is unknown")
            + " is unknown. An unknown condition is never treated as safe."
        )
    if fix is not None and fix.removes(delta.id):
        kept = sum(1 for r in fix.expected_after if r.result == "pass")
        verdict = "Verified in this model." if fix.verified_for(delta.id) else "Not verified: coverage is incomplete after the change."
        sentences.append(
            f"Revoking {fix.fact_id} on a copy removes the path and keeps {kept} of {len(fix.expected_after)} "
            f"normal access checks. {verdict}"
        )
    elif delta.status == "added":
        sentences.append("No single revocation of a newly enabled grant removes this path.")
    sentences.append("Nothing was deployed or executed.")
    return sentences
