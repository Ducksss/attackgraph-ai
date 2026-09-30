"""Test single-permission revocations on in-memory copies of the proposal.

A fix candidate is a grant that the baseline declared false and the proposal
turns true under the same fact ID, and that participates in a proposal
finding. Revoking it sets the state back to false on a copy: the record and
its provenance stay, because deleting a fact would make it unknown. Every
candidate is re-analysed in full; no derived edge is ever removed directly,
since another route could recreate it. The re-analysis reuses the proposal's
evaluated candidates whose inputs the revocation leaves unchanged (see
analysis.analyze), which gives the same result as starting from scratch.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

from .analysis import FALSE, TRUE, ExpectedAccessResult, SnapshotAnalysis, analyze
from .compare import Comparison
from .snapshot import Fact

# Each candidate is a full re-analysis; the cap bounds the worst case for large uploads.
MAX_FIX_CANDIDATES = 25


@dataclass(frozen=True, eq=False)
class FixCandidate:
    id: str
    fact_id: str
    baseline_fact: Fact
    proposal_fact: Fact
    proposal: SnapshotAnalysis
    simulated: SnapshotAnalysis
    removed: tuple[str, ...]
    remaining: tuple[str, ...]
    now_inconclusive: tuple[str, ...]
    rank: int = 0  # 1-based among complete candidates; 0 when coverage is incomplete

    @property
    def coverage_complete(self) -> bool:
        return self.simulated.coverage.complete

    @property
    def expected_after(self) -> tuple[ExpectedAccessResult, ...]:
        return self.simulated.expected_access

    @property
    def failed_expected(self) -> int:
        return sum(1 for r in self.simulated.expected_access if r.result != "pass")

    @property
    def expected_changes(self) -> tuple[tuple[str, str, str], ...]:
        changes = []
        for before in self.proposal.expected_access:
            after = self.simulated.expected_result(before.check.id)
            if after is not None and after.result != before.result:
                changes.append((before.check.id, before.result, after.result))
        return tuple(changes)

    def removes(self, finding_id: str) -> bool:
        return finding_id in self.removed

    def verified_for(self, finding_id: str) -> bool:
        """Verified in this model: recomputation removes the finding with complete coverage."""
        return self.coverage_complete and self.removes(finding_id)

    def describe(self) -> str:
        return f"Revoke {self.fact_id}: {self.proposal_fact.describe()}"


def _closure(adjacency: dict[str, set[str]], start: set[str]) -> set[str]:
    seen, stack = set(start), list(start)
    while stack:
        for node in adjacency.get(stack.pop(), ()):
            if node not in seen:
                seen.add(node)
                stack.append(node)
    return seen


def participating_fact_ids(analysis: SnapshotAnalysis) -> frozenset[str]:
    """Facts on some established route from an entry principal to a finding's target.

    The established edges are the candidates whose state is true. An edge is on
    such a route when its subject is reachable from the finding's entry and its
    target reaches the finding's target. Findings that share an entry share the
    first condition, so each entry is walked once, backwards from all of its
    targets together.
    """
    edges = [c for c in analysis.candidates.values() if c.state == TRUE]
    forward: dict[str, set[str]] = defaultdict(set)
    backward: dict[str, set[str]] = defaultdict(set)
    for c in edges:
        forward[c.subject].add(c.target)
        backward[c.target].add(c.subject)
    targets: dict[str, set[str]] = defaultdict(set)
    for finding in analysis.findings.values():
        targets[finding.entry].add(finding.target)
    ids: set[str] = set()
    for entry, finding_targets in targets.items():
        reach, coreach = _closure(forward, {entry}), _closure(backward, finding_targets)
        for c in edges:
            if c.subject in reach and c.target in coreach:
                ids.update(c.fact_ids)
    return frozenset(ids)


def eligible_grants(comparison: Comparison) -> tuple[str, ...]:
    """Newly enabled permission or trust facts on a route to a proposal finding."""
    participating = participating_fact_ids(comparison.proposal)
    return tuple(
        change.fact_id
        for change in comparison.fact_changes
        if change.newly_enabled
        and change.fact_id in participating
        and change.proposal.spec.category != "assumption"
    )


def fix_candidates(comparison: Comparison, limit: int = MAX_FIX_CANDIDATES) -> tuple[FixCandidate, ...]:
    """Simulate up to `limit` eligible revocations, in fact-ID order."""
    proposal = comparison.proposal
    tested: list[FixCandidate] = []
    for fact_id in eligible_grants(comparison)[:limit]:
        change = comparison.fact_change(fact_id)
        simulated = analyze(proposal.snapshot.with_fact_state(change.fact_id, FALSE), reuse=proposal)
        tested.append(
            FixCandidate(
                id=f"revoke/{change.fact_id}",
                fact_id=change.fact_id,
                baseline_fact=change.baseline,
                proposal_fact=change.proposal,
                proposal=proposal,
                simulated=simulated,
                removed=tuple(k for k in sorted(proposal.findings) if simulated.state_of(k) == "unreachable"),
                remaining=tuple(k for k in sorted(proposal.findings) if simulated.state_of(k) == "reachable"),
                now_inconclusive=tuple(k for k in sorted(proposal.findings) if simulated.state_of(k) == "inconclusive"),
            )
        )

    complete = sorted(
        (c for c in tested if c.coverage_complete),
        key=lambda c: (c.failed_expected, -len(c.removed), c.fact_id),
    )
    ranked = [replace(c, rank=i) for i, c in enumerate(complete, start=1)]
    incomplete = sorted((c for c in tested if not c.coverage_complete), key=lambda c: c.fact_id)
    return tuple(ranked + incomplete)


def best_fix_for(candidates: tuple[FixCandidate, ...], finding_id: str) -> FixCandidate | None:
    """Top-ranked candidate verified to remove the finding; ranking prefers preserved expected access."""
    return next((c for c in candidates if c.verified_for(finding_id)), None)
