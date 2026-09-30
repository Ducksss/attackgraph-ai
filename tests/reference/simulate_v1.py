# FROZEN ORACLE. A verbatim copy of attackgraph/simulate.py at commit a222929, the engine
# before the Rule B performance work. tests/test_differential.py runs it beside the
# live engine and requires identical results. Do not edit, reformat or fix it: only
# the imports differ from the original, so that the copies use each other.

"""Test single-permission revocations on in-memory copies of the proposal.

A fix candidate is a grant that the baseline declared false and the proposal
turns true under the same fact ID, and that participates in a proposal
finding. Revoking it sets the state back to false on a copy: the record and
its provenance stay, because deleting a fact would make it unknown. Every
candidate is re-analysed from scratch; no derived edge is ever removed
directly, since another route could recreate it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import networkx as nx

from .analysis_v1 import FALSE, ExpectedAccessResult, SnapshotAnalysis, analyze
from .compare_v1 import Comparison
from attackgraph.snapshot import Fact

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


def participating_fact_ids(analysis: SnapshotAnalysis) -> frozenset[str]:
    """Facts on some established route from an entry principal to a finding's target."""
    graph = analysis.established_graph
    ids: set[str] = set()
    for finding in analysis.findings.values():
        reach = nx.descendants(graph, finding.entry) | {finding.entry}
        coreach = nx.ancestors(graph, finding.target) | {finding.target}
        for u, v, data in graph.edges(data=True):
            if u in reach and v in coreach:
                ids.update(data["candidate"].fact_ids)
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
        simulated = analyze(proposal.snapshot.with_fact_state(change.fact_id, FALSE))
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
