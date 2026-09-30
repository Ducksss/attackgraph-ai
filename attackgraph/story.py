"""Plain-language view of one finding for the judge-facing walkthrough.

Everything here is derived from engine objects; nothing is inferred. The
strings include node labels, which are untrusted display text, so callers
must escape them before rendering.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import FALSE, RULE_LAMBDA, UNKNOWN, Candidate, Finding, PotentialFinding, Prerequisite
from .compare import Comparison, FindingDelta
from .snapshot import POLICY_CONTROLS, Snapshot

KIND_NAMES = {"principal": "Entry point", "role": "IAM role", "lambda": "Lambda function", "s3_object": "S3 object"}

# Rule B prerequisites grouped by the visual hop they belong to.
_TO_WORKLOAD = {"iam_pass_role_to_lambda", "lambda_create_function", "lambda_invoke_function", "controls_workload_code"}


@dataclass(frozen=True)
class Condition:
    text: str
    state: str
    key: str
    change: str | None  # "false → true" when the condition differs between the snapshots
    assumption: bool
    fact_id: str | None
    pointers: tuple[str, ...]
    reason: str = ""  # why the condition is unknown, as a sentence; empty unless it is


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
    unknown: bool = False  # one of this hop's own conditions is unknown


@dataclass(frozen=True)
class Step:
    candidate: Candidate
    title: str
    conditions: tuple[Condition, ...]
    baseline_state: str | None  # the same candidate in the baseline; None when never evaluated there
    baseline_blockers: tuple[str, ...]  # the conditions that were false there


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
        "controls_workload_code": f"{subject} controls the code that {via} runs",
        "role_trusts_lambda_service": f"{target} trusts the Lambda service",
        "same_account": "Everything is in one AWS account",
        "policy_controls_resolved": "No unresolved policy restrictions apply",
        "s3_get_object": f"{subject} can read {target}",
    }[key]


def _verb(impact: str) -> str:
    return "run code as" if impact == "privileged_role_use" else "read"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def unknown_reason(p: Prerequisite, text: str, snapshot: Snapshot) -> str:
    """Why a condition is unknown, as a sentence; empty when it is not."""
    if p.state != UNKNOWN:
        return ""
    if p.key == "policy_controls_resolved":
        controls = [POLICY_CONTROLS[k].lower() for k, v in snapshot.policy_controls.items() if v != "resolved"]
        return f"The snapshot marks {_join(controls or ['policy restrictions'])} as unresolved, so they could block this route."
    if p.key == "same_account":
        return "The route crosses AWS accounts, which this model does not evaluate."
    if p.origin == "missing":
        return f"No fact says whether {text}."
    return f"It is unknown whether {text}."


def headline(delta: FindingDelta, snapshot: Snapshot) -> str:
    entry, target, verb = label(snapshot, delta.entry), label(snapshot, delta.target), _verb(delta.impact)
    if delta.status != "inconclusive":
        return {
            "added": f"{entry} can now {verb} {target}",
            "removed": f"{entry} can no longer {verb} {target}",
            "unchanged": f"{entry} can still {verb} {target}",
        }[delta.status]
    # Lead with what the proposal establishes; only the comparison is unresolved.
    return {
        "reachable": f"{entry} can {verb} {target} in the proposal",
        "unreachable": f"{entry} cannot {verb} {target} in the proposal",
        "inconclusive": f"Unresolved: can {entry} {verb} {target}?",
    }.get(delta.proposal_state, f"Unresolved: could {entry} {verb} {target} before the change?")


def build_story(comparison: Comparison, delta: FindingDelta) -> Story:
    record = delta.current
    analysis = comparison.proposal if delta.proposal is not None else comparison.baseline
    other = comparison.baseline if delta.proposal is not None else comparison.proposal
    snapshot = analysis.snapshot
    witness = record.witness if isinstance(record, Finding) else record.possible_witness
    changed_ids = comparison.changed_fact_ids

    def change_of(candidate: Candidate, p: Prerequisite) -> str | None:
        """Baseline to proposal: a changed fact, or a check whose result differs in the other snapshot."""
        if p.fact_id:
            change = comparison.fact_change(p.fact_id) if p.fact_id in changed_ids else None
            return f"{change.before} → {change.after}" if change else None
        twin = other.candidates.get(candidate.id)
        state = next((q.state for q in twin.prerequisites if q.key == p.key), None) if twin else None
        if state is None or state == p.state:
            return None
        return f"{state} → {p.state}" if other is comparison.baseline else f"{p.state} → {state}"

    def condition(candidate: Candidate, p: Prerequisite) -> Condition:
        text = condition_text(p.key, candidate, snapshot)
        return Condition(
            text=text,
            state=p.state,
            key=p.key,
            change=change_of(candidate, p),
            assumption=p.assumption,
            fact_id=p.fact_id,
            pointers=p.pointers,
            reason=unknown_reason(p, text, snapshot),
        )

    nodes: list[PathNode] = []
    hops: list[Hop] = []
    steps: list[Step] = []

    def add_node(node_id: str) -> None:
        node = snapshot.nodes[node_id]
        target = snapshot.protected_targets.get(node_id)
        nodes.append(PathNode(node_id, node.kind, node.label, target.classification if target else None))

    def hop(text: str, candidate: Candidate, group: tuple[Prerequisite, ...]) -> Hop:
        fact_ids = tuple(p.fact_id for p in group if p.fact_id)
        unknown = any(p.state == UNKNOWN for p in group)
        return Hop(text, bool(set(fact_ids) & changed_ids), fact_ids, candidate.state, unknown)

    for candidate in witness:
        if not nodes:
            add_node(candidate.subject)
        if candidate.rule == RULE_LAMBDA:
            first = tuple(p for p in candidate.prerequisites if p.key in _TO_WORKLOAD)
            second = tuple(p for p in candidate.prerequisites if p.key not in _TO_WORKLOAD)
            hops.append(hop(f"can pass {label(snapshot, candidate.target)} to", candidate, first))
            add_node(candidate.via)
            hops.append(hop("runs as", candidate, second))
            title = (
                f"{label(snapshot, candidate.subject)} can run code as {label(snapshot, candidate.target)} "
                f"through {label(snapshot, candidate.via)}"
            )
        else:
            hops.append(hop("can read", candidate, candidate.prerequisites))
            title = f"{label(snapshot, candidate.subject)} can read {label(snapshot, candidate.target)}"
        add_node(candidate.target)

        conditions = [condition(candidate, p) for p in candidate.prerequisites]
        conditions.sort(key=lambda c: c.change is None)  # changed conditions first, stable otherwise
        before = comparison.baseline.candidates.get(candidate.id)
        blockers = tuple(p.fact_id or p.key for p in (before.prerequisites if before else ()) if p.state == FALSE)
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


def _change_items(conditions) -> list[str]:
    return [f"{c.text} ({c.change.replace(' → ', ' to ')})" for c in conditions]


def _changed(conditions) -> str:
    """'The proposal changes one condition: X (false to true).'"""
    items = _change_items(conditions)
    lead = "The proposal changes one condition" if len(items) == 1 else f"The proposal changes {len(items)} conditions"
    return f"{lead}: {'; '.join(items)}."


def _unresolved(story: Story) -> list[str]:
    """What the proposal establishes first, then exactly which condition is unknown."""
    delta = story.delta
    entry, target, verb = story.nodes[0].label, story.nodes[-1].label, _verb(delta.impact)
    reasons = [c.reason for c in story.conditions if c.reason]
    if delta.proposal_state == "reachable":
        sentences = [story.headline + "."]
        if story.changes:
            sentences.append(_changed(story.changes))
        sentences.append(
            f"All {len(story.conditions)} conditions on this route hold in the proposal, but the baseline could not be "
            "resolved, so the engine cannot say whether the route is new."
        )
        return sentences
    if delta.proposal is None:
        if delta.proposal_state == "unreachable":
            sentences = [f"In the proposal, {entry} cannot {verb} {target}."]
        else:
            sentences = ["The proposal no longer checks this route."]
        sentences.append("The baseline could not be resolved, so the engine cannot say whether the change closed a route.")
        return sentences + [f"In the baseline, {r[0].lower()}{r[1:]}" for r in reasons]
    sentences = [f"It is unresolved whether {entry} can {verb} {target}."]
    known = [c for c in story.changes if c.state != UNKNOWN]  # a change to unknown is explained by its reason
    if known:
        sentences.append(_changed(known))
    sentences += reasons or ["A condition on this route is unknown."]
    sentences.append("An unknown condition is never treated as safe.")
    return sentences


def summary(story: Story, fix=None) -> list[str]:
    """Deterministic plain-language sentences; shown when no AI explanation is on screen."""
    delta = story.delta
    held = len(story.conditions)
    if delta.status == "inconclusive":
        sentences = _unresolved(story)
    elif delta.status == "added":
        sentences = [story.headline + "."]
        if story.changes:
            sentences += [_changed(story.changes), f"With it, all {held} conditions on this route hold."]
        else:
            sentences.append(f"All {held} conditions on this route hold.")
    elif delta.status == "removed":
        sentences = [story.headline + "."]
        if story.changes:
            sentences.append(f"The second snapshot changes: {'; '.join(_change_items(story.changes))}.")
    else:
        sentences = [story.headline + ".", "The route exists in both snapshots."]
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
