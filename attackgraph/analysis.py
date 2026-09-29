"""Derive supported relationships and find reachable protected targets.

Each rule is an AND over explicit prerequisites, evaluated with three-valued
logic: any false prerequisite blocks a candidate; otherwise any unknown one
leaves it unresolved; otherwise the candidate is established. Only
established candidates become witness edges. Unresolved candidates make
coverage incomplete and can only produce inconclusive results, never a safe
verdict.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from functools import cached_property
from typing import Iterable

import networkx as nx

from .snapshot import (
    POLICY_CONTROLS,
    PREDICATES,
    UNMODELLED_MECHANISMS,
    ExpectedAccess,
    Snapshot,
    pointer,
)

TRUE, FALSE, UNKNOWN = "true", "false", "unknown"

RULE_S3 = "s3_direct_read"
RULE_LAMBDA = "lambda_pass_role"
RULE_TITLES = {
    RULE_S3: "Rule A: direct S3 object read",
    RULE_LAMBDA: "Rule B: role use through a Lambda workload",
}
IMPACTS = {"privileged_role": "privileged_role_use", "sensitive_object": "sensitive_object_read"}
IMPACT_TITLES = {"privileged_role_use": "privileged role use", "sensitive_object_read": "sensitive object read"}
SEVERITY_HIGH = "High"


def kleene_and(states: Iterable[str]) -> str:
    states = tuple(states)
    if FALSE in states:
        return FALSE
    if UNKNOWN in states:
        return UNKNOWN
    return TRUE


def finding_id(entry: str, target: str, impact: str) -> str:
    # IDs cannot contain '/', so the separator is unambiguous.
    return f"finding/{entry}/{target}/{impact}"


@dataclass(frozen=True)
class Prerequisite:
    key: str
    text: str
    state: str
    origin: str  # fact | missing | derived
    fact_id: str | None = None
    pointers: tuple[str, ...] = ()
    assumption: bool = False
    note: str = ""

    def unresolved_reason(self) -> str:
        if self.origin == "missing":
            return f"no fact declares that {self.text}"
        if self.origin == "fact":
            return f"fact {self.fact_id} ({self.text}) is unknown"
        return f"{self.text}: {self.note}"


@dataclass(frozen=True)
class Candidate:
    id: str
    rule: str
    subject: str
    target: str
    via: str | None
    prerequisites: tuple[Prerequisite, ...]
    state: str

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(p.fact_id for p in self.prerequisites if p.fact_id)

    @property
    def sort_key(self) -> tuple:
        return (tuple(sorted(self.fact_ids)), self.id)

    def describe(self) -> str:
        if self.rule == RULE_S3:
            return f"{self.subject} can read {self.target}"
        return f"{self.subject} can run code as {self.target} through Lambda workload {self.via}"


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


@dataclass(frozen=True)
class Finding:
    id: str
    entry: str
    target: str
    impact: str
    classification: str
    witness: tuple[Candidate, ...]
    assumptions: tuple[str, ...]
    severity: str = SEVERITY_HIGH

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return _unique(fid for c in self.witness for fid in c.fact_ids)

    @property
    def pointers(self) -> tuple[str, ...]:
        return _unique(ptr for c in self.witness for p in c.prerequisites for ptr in p.pointers)

    @property
    def evidence_signature(self) -> tuple:
        # Pointers are left out: reordering arrays is not an evidence change.
        return tuple((c.id, tuple(sorted(c.fact_ids))) for c in self.witness)

    def describe(self) -> str:
        return describe_impact(self.entry, self.target, self.impact)


@dataclass(frozen=True)
class PotentialFinding:
    """A protected target reachable only through unresolved candidates."""

    id: str
    entry: str
    target: str
    impact: str
    classification: str
    possible_witness: tuple[Candidate, ...]
    severity: str = SEVERITY_HIGH

    @property
    def unresolved(self) -> tuple[tuple[Candidate, Prerequisite], ...]:
        return tuple((c, p) for c in self.possible_witness for p in c.prerequisites if p.state == UNKNOWN)

    def describe(self) -> str:
        return describe_impact(self.entry, self.target, self.impact)


def describe_impact(entry: str, target: str, impact: str) -> str:
    if impact == "privileged_role_use":
        return f"{entry} can use privileged role {target}"
    return f"{entry} can read sensitive object {target}"


@dataclass(frozen=True)
class ExpectedAccessResult:
    check: ExpectedAccess
    result: str  # pass | fail | inconclusive
    witness: tuple[Candidate, ...]


@dataclass(frozen=True)
class CoverageIssue:
    kind: str  # policy_control | unmodelled_mechanism | unresolved_candidate
    message: str
    pointers: tuple[str, ...] = ()
    candidate_id: str | None = None


@dataclass(frozen=True)
class Coverage:
    complete: bool
    issues: tuple[CoverageIssue, ...]
    candidate_counts: dict[str, dict[str, int]]
    subjects_evaluated: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, eq=False)
class SnapshotAnalysis:
    snapshot: Snapshot
    candidates: dict[str, Candidate]
    findings: dict[str, Finding]
    potential: dict[str, PotentialFinding]
    expected_access: tuple[ExpectedAccessResult, ...]
    coverage: Coverage
    graph: nx.MultiDiGraph

    @property
    def high_risk_count(self) -> int:
        return len(self.findings)

    @cached_property
    def established_graph(self) -> nx.MultiDiGraph:
        return established_view(self.graph)

    def state_of(self, finding_key: str) -> str:
        if finding_key in self.findings:
            return "reachable"
        if finding_key in self.potential:
            return "inconclusive"
        return "unreachable"

    def expected_result(self, check_id: str) -> ExpectedAccessResult | None:
        return next((r for r in self.expected_access if r.check.id == check_id), None)


def established_view(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    return nx.subgraph_view(
        graph, filter_edge=lambda u, v, k: graph.edges[u, v, k]["candidate"].state == TRUE
    )


def _fact_prerequisite(snapshot: Snapshot, predicate: str, subject: str, obj: str | None) -> Prerequisite:
    spec = PREDICATES[predicate]
    text = spec.describe(subject, obj)
    fact = snapshot.fact_for(predicate, subject, obj)
    if fact is None:
        return Prerequisite(predicate, text, UNKNOWN, "missing", note="not declared, so it evaluates to unknown")
    return Prerequisite(
        predicate,
        text,
        fact.state,
        "fact",
        fact.id,
        (fact.pointer,),
        assumption=spec.category == "assumption",
    )


def _policy_prerequisite(snapshot: Snapshot) -> Prerequisite:
    unresolved = [key for key in POLICY_CONTROLS if snapshot.policy_controls[key] != "resolved"]
    text = "policy restrictions are declared resolved for this scenario"
    if unresolved:
        return Prerequisite(
            "policy_controls_resolved",
            text,
            UNKNOWN,
            "derived",
            pointers=tuple(pointer("coverage", "policy_controls", key) for key in unresolved),
            note="declared unresolved: " + ", ".join(POLICY_CONTROLS[key].lower() for key in unresolved),
        )
    return Prerequisite("policy_controls_resolved", text, TRUE, "derived", pointers=(pointer("coverage", "policy_controls"),))


def _same_account_prerequisite(snapshot: Snapshot, subject: str, role: str, workload: str) -> Prerequisite:
    nodes = [snapshot.nodes[node_id] for node_id in (subject, role, workload)]
    pointers = tuple(f"{node.pointer}/account_id" for node in nodes)
    text = f"{subject}, {role} and {workload} are in the same synthetic account"
    if len({node.account_id for node in nodes}) == 1:
        return Prerequisite("same_account", text, TRUE, "derived", pointers=pointers)
    return Prerequisite(
        "same_account",
        text,
        UNKNOWN,
        "derived",
        pointers=pointers,
        note="cross-account configurations are outside the supported model",
    )


def _s3_candidate(snapshot: Snapshot, subject: str, obj: str, policy: Prerequisite) -> Candidate:
    prerequisites = (_fact_prerequisite(snapshot, "s3_get_object", subject, obj), policy)
    return Candidate(
        f"A:{subject}->{obj}",
        RULE_S3,
        subject,
        obj,
        None,
        prerequisites,
        kleene_and(p.state for p in prerequisites),
    )


def _lambda_candidate(snapshot: Snapshot, subject: str, role: str, workload: str, policy: Prerequisite) -> Candidate:
    prerequisites = (
        _fact_prerequisite(snapshot, "iam_pass_role_to_lambda", subject, role),
        _fact_prerequisite(snapshot, "lambda_create_function", subject, workload),
        _fact_prerequisite(snapshot, "lambda_invoke_function", subject, workload),
        _fact_prerequisite(snapshot, "controls_workload_code", subject, workload),
        _fact_prerequisite(snapshot, "role_trusts_lambda_service", role, None),
        _same_account_prerequisite(snapshot, subject, role, workload),
        policy,
    )
    return Candidate(
        f"B:{subject}->{role}@{workload}",
        RULE_LAMBDA,
        subject,
        role,
        workload,
        prerequisites,
        kleene_and(p.state for p in prerequisites),
    )


def _generate(snapshot: Snapshot) -> tuple[dict[str, Candidate], dict[str, tuple[Candidate, ...]], list[str]]:
    """Evaluate every candidate from subjects that are, or may be, reachable.

    Rule A covers S3 objects that are protected or named in an expected-access
    check, plus any object the subject has a declared s3_get_object fact for.
    Rule B covers every other role through every represented Lambda workload.
    Missing prerequisites are unknown, so an undeclared relationship from a
    reachable subject makes coverage incomplete rather than silently safe.
    """
    policy = _policy_prerequisite(snapshot)
    roles = snapshot.nodes_of_kind("role")
    workloads = snapshot.nodes_of_kind("lambda")
    relevant_objects = {
        t.node for t in snapshot.protected_targets.values() if t.classification == "sensitive_object"
    } | {c.target for c in snapshot.expected_access if c.relationship == "object_read"}
    declared_reads: dict[str, set[str]] = defaultdict(set)
    for fact in snapshot.facts.values():
        if fact.predicate == "s3_get_object":
            declared_reads[fact.subject].add(fact.object)

    candidates: dict[str, Candidate] = {}
    by_subject: dict[str, tuple[Candidate, ...]] = {}
    queue = deque(sorted(snapshot.entry_principals))
    while queue:
        subject = queue.popleft()
        if subject in by_subject:
            continue
        outgoing = [
            _s3_candidate(snapshot, subject, obj, policy)
            for obj in sorted(relevant_objects | declared_reads.get(subject, set()))
        ]
        for role in roles:
            if role == subject:
                continue
            for workload in workloads:
                candidate = _lambda_candidate(snapshot, subject, role, workload, policy)
                outgoing.append(candidate)
                if candidate.state != FALSE and role not in by_subject:
                    queue.append(role)
        by_subject[subject] = tuple(outgoing)
        candidates.update((c.id, c) for c in outgoing)

    notes = [
        "Candidates are evaluated for every subject that is reachable, or possibly reachable, from an entry principal.",
        "Rule A evaluates S3 objects that are protected or named in an expected-access check, plus objects with a declared s3_get_object fact.",
    ]
    if not workloads:
        notes.append("No Lambda workload is represented, so Rule B has no candidates.")
    return candidates, by_subject, notes


def _witnesses(graph: nx.MultiDiGraph, source: str) -> dict[str, tuple[Candidate, ...]]:
    """Shortest witness to every reachable node, ties broken by fact IDs.

    Layered BFS with a visited set: each node is settled at its first layer,
    so cycles terminate and all simple paths are never enumerated.
    """
    best: dict[str, tuple[Candidate, ...]] = {source: ()}
    layer = [source]
    while layer:
        reached: dict[str, tuple[Candidate, ...]] = {}
        for node in layer:
            for _, target, data in graph.out_edges(node, data=True):
                if target in best:
                    continue
                path = best[node] + (data["candidate"],)
                if target not in reached or _path_key(path) < _path_key(reached[target]):
                    reached[target] = path
        best.update(reached)
        layer = sorted(reached)
    return best


def _path_key(path: tuple[Candidate, ...]) -> tuple:
    return tuple(c.sort_key for c in path)


def _assumptions(entry: str, witness: tuple[Candidate, ...]) -> tuple[str, ...]:
    out = [
        f"Entry principal {entry} is treated as controlled by the party proposing the change. "
        "This is a scenario assumption, not an inferred compromise."
    ]
    for candidate in witness:
        for p in candidate.prerequisites:
            if p.assumption and p.state == TRUE:
                out.append(f"{p.text} (scenario assumption, fact {p.fact_id}).")
    out.append(
        "Declared facts stand for resolved synthetic model inputs; they are not evidence "
        "that AWS would authorise the same request in a real account."
    )
    return _unique(out)


def _coverage(snapshot: Snapshot, candidates: dict[str, Candidate], by_subject: dict, notes: list[str]) -> Coverage:
    issues: list[CoverageIssue] = []
    for key, title in POLICY_CONTROLS.items():
        if snapshot.policy_controls[key] != "resolved":
            issues.append(
                CoverageIssue(
                    "policy_control",
                    f"{title} are declared unresolved: their effect is not reflected in the declared facts, "
                    "so no candidate can be established.",
                    (pointer("coverage", "policy_controls", key),),
                )
            )
    for i, mechanism in enumerate(snapshot.unmodelled_mechanisms):
        issues.append(
            CoverageIssue(
                "unmodelled_mechanism",
                f"{UNMODELLED_MECHANISMS[mechanism]} declared: this model does not evaluate it, "
                "so other access routes may exist.",
                (pointer("coverage", "unmodelled_mechanisms", i),),
            )
        )
    counts: dict[str, Counter] = {RULE_S3: Counter(), RULE_LAMBDA: Counter()}
    for candidate in sorted(candidates.values(), key=lambda c: c.id):
        counts[candidate.rule][candidate.state] += 1
        if candidate.state == UNKNOWN:
            unknown = [p for p in candidate.prerequisites if p.state == UNKNOWN]
            issues.append(
                CoverageIssue(
                    "unresolved_candidate",
                    f"{candidate.describe()}: unresolved because " + "; ".join(p.unresolved_reason() for p in unknown),
                    _unique(ptr for p in unknown for ptr in p.pointers),
                    candidate.id,
                )
            )
    return Coverage(
        complete=not issues,
        issues=tuple(issues),
        candidate_counts={rule: {s: c[s] for s in (TRUE, FALSE, UNKNOWN)} for rule, c in counts.items()},
        subjects_evaluated=tuple(sorted(by_subject)),
        notes=tuple(notes),
    )


def _expected(check: ExpectedAccess, definite: dict, possible: dict) -> ExpectedAccessResult:
    if check.target in definite:
        return ExpectedAccessResult(check, "pass", definite[check.target])
    if check.target in possible:
        return ExpectedAccessResult(check, "inconclusive", possible[check.target])
    return ExpectedAccessResult(check, "fail", ())


def analyze(snapshot: Snapshot) -> SnapshotAnalysis:
    candidates, by_subject, notes = _generate(snapshot)
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(sorted(snapshot.nodes))
    for candidate in sorted(candidates.values(), key=lambda c: c.id):
        if candidate.state != FALSE:
            graph.add_edge(candidate.subject, candidate.target, key=candidate.id, candidate=candidate)
    established = established_view(graph)

    findings: dict[str, Finding] = {}
    potential: dict[str, PotentialFinding] = {}
    definite_by_entry: dict[str, dict] = {}
    possible_by_entry: dict[str, dict] = {}
    for entry in sorted(snapshot.entry_principals):
        definite = definite_by_entry[entry] = _witnesses(established, entry)
        possible = possible_by_entry[entry] = _witnesses(graph, entry)
        for target_id in sorted(snapshot.protected_targets):
            target = snapshot.protected_targets[target_id]
            impact = IMPACTS[target.classification]
            key = finding_id(entry, target_id, impact)
            if target_id in definite:
                witness = definite[target_id]
                findings[key] = Finding(key, entry, target_id, impact, target.classification, witness, _assumptions(entry, witness))
            elif target_id in possible:
                potential[key] = PotentialFinding(key, entry, target_id, impact, target.classification, possible[target_id])

    expected = tuple(
        _expected(check, definite_by_entry[check.principal], possible_by_entry[check.principal])
        for check in snapshot.expected_access
    )
    return SnapshotAnalysis(
        snapshot=snapshot,
        candidates=candidates,
        findings=findings,
        potential=potential,
        expected_access=expected,
        coverage=_coverage(snapshot, candidates, by_subject, notes),
        graph=graph,
    )
