"""Compare the findings of two analysed snapshots.

Finding identity is (entry principal, protected target, impact kind), so
array order and display labels never change which finding is which. A delta
is confirmed only when both snapshots have complete coverage; otherwise every
label is provisional, because an absent witness in an incomplete model cannot
show that access was added or removed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cached_property

from . import ENGINE_VERSION, MODEL_VERSION
from .analysis import (
    FALSE,
    IMPACTS,
    TRUE,
    Finding,
    PotentialFinding,
    SnapshotAnalysis,
    analyze,
)
from .snapshot import POLICY_CONTROLS, Fact, Snapshot

STATUS_ORDER = {"added": 0, "inconclusive": 1, "unchanged": 2, "removed": 3}


def analysis_id(baseline: Snapshot, proposal: Snapshot) -> str:
    def revisions(s: Snapshot) -> str:
        return ",".join(f"{r.fact_id}:{r.from_state}>{r.to_state}" for r in s.revisions)

    material = "|".join(
        [ENGINE_VERSION, MODEL_VERSION, baseline.sha256, revisions(baseline), proposal.sha256, revisions(proposal)]
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class FactChange:
    fact_id: str
    baseline: Fact | None
    proposal: Fact | None

    @property
    def kind(self) -> str:
        if self.baseline is None:
            return "added"
        if self.proposal is None:
            return "removed"
        if self.baseline.triple != self.proposal.triple:
            return "redefined"
        return "state_changed"

    @property
    def newly_enabled(self) -> bool:
        """An explicit false grant that the proposal turns true under the same ID."""
        return (
            self.kind == "state_changed"
            and self.baseline.state == FALSE
            and self.proposal.state == TRUE
        )

    def describe(self) -> str:
        fact = self.proposal or self.baseline
        return fact.describe()

    @property
    def before(self) -> str:
        return self.baseline.state if self.baseline else "absent (unknown)"

    @property
    def after(self) -> str:
        return self.proposal.state if self.proposal else "absent (unknown)"


@dataclass(frozen=True)
class ConfigChange:
    kind: str
    subject: str
    before: str
    after: str

    def describe(self) -> str:
        return f"{self.subject}: {self.before} → {self.after}"


@dataclass(frozen=True)
class FindingDelta:
    id: str
    entry: str
    target: str
    impact: str
    classification: str
    baseline_state: str  # reachable | unreachable | inconclusive | out_of_scope
    proposal_state: str
    status: str  # added | removed | unchanged | inconclusive
    provisional: bool
    evidence_changed: bool
    baseline: Finding | PotentialFinding | None
    proposal: Finding | PotentialFinding | None
    severity: str = "High"

    @property
    def confirmed(self) -> bool:
        return not self.provisional and self.status != "inconclusive"

    @property
    def current(self) -> Finding | PotentialFinding | None:
        """The record that carries the evidence to display."""
        return self.proposal if self.proposal is not None else self.baseline

    def describe(self) -> str:
        return self.current.describe()


def _state(analysis: SnapshotAnalysis, key: str, entry: str, target: str) -> str:
    snapshot = analysis.snapshot
    if entry not in snapshot.entry_principals or target not in snapshot.protected_targets:
        return "out_of_scope"
    return analysis.state_of(key)


def _status(before: str, after: str) -> str:
    if "inconclusive" in (before, after):
        return "inconclusive"
    if before == "reachable" and after == "reachable":
        return "unchanged"
    if after == "reachable":
        return "added"
    return "removed"


@dataclass(frozen=True, eq=False)
class Comparison:
    analysis_id: str
    baseline: SnapshotAnalysis
    proposal: SnapshotAnalysis
    deltas: tuple[FindingDelta, ...]
    fact_changes: tuple[FactChange, ...]
    config_changes: tuple[ConfigChange, ...]

    @property
    def complete(self) -> bool:
        return self.baseline.coverage.complete and self.proposal.coverage.complete

    @property
    def verdict(self) -> str:
        if not self.complete:
            return "incomplete"
        if any(d.status == "added" for d in self.deltas):
            return "new_high_risk"
        return "no_new_high_risk"

    def delta(self, key: str) -> FindingDelta | None:
        return next((d for d in self.deltas if d.id == key), None)

    def count(self, status: str) -> int:
        return sum(1 for d in self.deltas if d.status == status)

    @cached_property
    def changed_fact_ids(self) -> frozenset[str]:
        return frozenset(c.fact_id for c in self.fact_changes)

    def fact_change(self, fact_id: str) -> FactChange | None:
        return next((c for c in self.fact_changes if c.fact_id == fact_id), None)


def _fact_changes(baseline: Snapshot, proposal: Snapshot) -> tuple[FactChange, ...]:
    changes = []
    for fact_id in sorted(set(baseline.facts) | set(proposal.facts)):
        before, after = baseline.facts.get(fact_id), proposal.facts.get(fact_id)
        if before and after and before.triple == after.triple and before.state == after.state:
            continue
        changes.append(FactChange(fact_id, before, after))
    return tuple(changes)


def _config_changes(baseline: Snapshot, proposal: Snapshot) -> tuple[ConfigChange, ...]:
    changes: list[ConfigChange] = []
    for node_id in sorted(set(baseline.protected_targets) | set(proposal.protected_targets)):
        before = baseline.protected_targets.get(node_id)
        after = proposal.protected_targets.get(node_id)
        b = before.classification if before else "not protected"
        a = after.classification if after else "not protected"
        if a != b:
            changes.append(ConfigChange("target_classification", node_id, b, a))
    for entry in sorted(set(baseline.entry_principals) ^ set(proposal.entry_principals)):
        in_proposal = entry in proposal.entry_principals
        changes.append(
            ConfigChange(
                "entry_principal",
                entry,
                "entry principal" if not in_proposal else "not an entry principal",
                "entry principal" if in_proposal else "not an entry principal",
            )
        )
    for key, title in POLICY_CONTROLS.items():
        if baseline.policy_controls[key] != proposal.policy_controls[key]:
            changes.append(ConfigChange("policy_control", title, baseline.policy_controls[key], proposal.policy_controls[key]))
    before_m, after_m = set(baseline.unmodelled_mechanisms), set(proposal.unmodelled_mechanisms)
    for mechanism in sorted(before_m ^ after_m):
        changes.append(
            ConfigChange(
                "unmodelled_mechanism",
                mechanism,
                "declared" if mechanism in before_m else "not declared",
                "declared" if mechanism in after_m else "not declared",
            )
        )
    for node_id in sorted(set(baseline.nodes) | set(proposal.nodes)):
        before, after = baseline.nodes.get(node_id), proposal.nodes.get(node_id)
        if before is None or after is None:
            changes.append(
                ConfigChange("node", node_id, "absent" if before is None else before.kind, "absent" if after is None else after.kind)
            )
            continue
        if before.kind != after.kind:
            changes.append(ConfigChange("node_kind", node_id, before.kind, after.kind))
        if before.account_id != after.account_id:
            changes.append(ConfigChange("node_account", node_id, before.account_id, after.account_id))
        if before.label != after.label:
            changes.append(ConfigChange("node_label", node_id, "label changed", "display only; no effect on analysis"))
    return tuple(changes)


def compare(baseline: SnapshotAnalysis, proposal: SnapshotAnalysis) -> Comparison:
    provisional = not (baseline.coverage.complete and proposal.coverage.complete)
    records: dict[str, Finding | PotentialFinding] = {}
    for analysis in (baseline, proposal):
        for record in (*analysis.findings.values(), *analysis.potential.values()):
            records.setdefault(record.id, record)

    deltas = []
    for key, record in records.items():
        before = _state(baseline, key, record.entry, record.target)
        after = _state(proposal, key, record.entry, record.target)
        status = _status(before, after)
        b_record = baseline.findings.get(key) or baseline.potential.get(key)
        p_record = proposal.findings.get(key) or proposal.potential.get(key)
        evidence_changed = (
            status == "unchanged" and b_record.evidence_signature != p_record.evidence_signature
        )
        classification = (p_record or b_record).classification
        deltas.append(
            FindingDelta(
                id=key,
                entry=record.entry,
                target=record.target,
                impact=IMPACTS[classification],
                classification=classification,
                baseline_state=before,
                proposal_state=after,
                status=status,
                provisional=provisional,
                evidence_changed=evidence_changed,
                baseline=b_record,
                proposal=p_record,
            )
        )
    deltas.sort(key=lambda d: (STATUS_ORDER[d.status], d.id))
    return Comparison(
        analysis_id=analysis_id(baseline.snapshot, proposal.snapshot),
        baseline=baseline,
        proposal=proposal,
        deltas=tuple(deltas),
        fact_changes=_fact_changes(baseline.snapshot, proposal.snapshot),
        config_changes=_config_changes(baseline.snapshot, proposal.snapshot),
    )


def compare_snapshots(baseline: Snapshot, proposal: Snapshot) -> Comparison:
    return compare(analyze(baseline), analyze(proposal))
