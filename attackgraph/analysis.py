"""Derive supported relationships and find reachable protected targets.

Each rule is an AND over explicit prerequisites, evaluated with three-valued
logic: any false prerequisite blocks a candidate; otherwise any unknown one
leaves it unresolved; otherwise the candidate is established. Only
established candidates become witness edges. Unresolved candidates make
coverage incomplete and can only produce inconclusive results, never a safe
verdict.

Rule B has a candidate for every evaluated subject, every other role and
every Lambda workload, so a file at the input limits can have well over
100,000. They are evaluated one row at a time, a row being one subject and
one role across all workloads, and each row is memoised under every input it
reads: the facts, node accounts and pointers involved, the workload list and
the policy prerequisite. An analysis that reuses another (the proposal after
the baseline, a fix simulation after the proposal) takes the rows whose
inputs are unchanged and evaluates the rest. Which subjects are evaluated,
the witnesses, coverage and findings are always recomputed in full.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
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


# kleene_and as a minimum: false < unknown < true, and any other value counts as true, as it does there.
_STATES = (FALSE, UNKNOWN, TRUE)


def _rank(state: str) -> int:
    return 0 if state == FALSE else 1 if state == UNKNOWN else 2


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


class _Memo:
    """Evaluated candidates keyed by every input they read, so equal inputs are evaluated once.

    A key holds values, never object identities, so analyses of different
    snapshots can share one memo: a row is taken only when every fact, node
    account and pointer, workload and policy state it depends on is equal.
    """

    def __init__(self) -> None:
        self.s3: dict[tuple, _S3Part] = {}
        self.contexts: dict[tuple, _Context] = {}


@dataclass(frozen=True, eq=False)
class SnapshotAnalysis:
    snapshot: Snapshot
    candidates: dict[str, Candidate]
    findings: dict[str, Finding]
    potential: dict[str, PotentialFinding]
    expected_access: tuple[ExpectedAccessResult, ...]
    coverage: Coverage
    _memo: _Memo = field(default_factory=_Memo, repr=False)

    @property
    def high_risk_count(self) -> int:
        return len(self.findings)

    @cached_property
    def graph(self) -> nx.MultiDiGraph:
        """Every candidate that is not blocked, as an edge keyed by its ID; built on first use."""
        graph = nx.MultiDiGraph()
        graph.add_nodes_from(sorted(self.snapshot.nodes))
        for candidate in sorted(self.candidates.values(), key=lambda c: c.id):
            if candidate.state != FALSE:
                graph.add_edge(candidate.subject, candidate.target, key=candidate.id, candidate=candidate)
        return graph

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


def _same_account_prerequisite(subject: str, role: str, workload: str, same: bool, pointers: tuple[str, ...]) -> Prerequisite:
    """same is whether the three nodes share one account_id; pointers are their account_id pointers, in order."""
    text = f"{subject}, {role} and {workload} are in the same synthetic account"
    if same:
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


def _unresolved_issue(candidate: Candidate) -> CoverageIssue:
    reasons, pointers = _unknown(candidate.prerequisites)
    return _issue(candidate, reasons, pointers)


def _unknown(prerequisites: Iterable[Prerequisite]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The reasons and pointers of the unknown prerequisites, in prerequisite order."""
    unknown = [p for p in prerequisites if p.state == UNKNOWN]
    return tuple(p.unresolved_reason() for p in unknown), tuple(ptr for p in unknown for ptr in p.pointers)


def _issue(candidate: Candidate, reasons: tuple[str, ...], pointers: tuple[str, ...]) -> CoverageIssue:
    """The coverage issue of an unknown candidate, from the _unknown() of its prerequisites."""
    return CoverageIssue(
        "unresolved_candidate",
        f"{candidate.describe()}: unresolved because " + "; ".join(reasons),
        _unique(pointers) if pointers else (),
        candidate.id,
    )


class _Inputs:
    """What candidate evaluation reads from one snapshot, indexed once per analysis."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.policy = _policy_prerequisite(snapshot)
        self.policy_unknown = _unknown((self.policy,))
        self.roles = snapshot.nodes_of_kind("role")
        self.workloads = snapshot.nodes_of_kind("lambda")
        self.objects = {
            t.node for t in snapshot.protected_targets.values() if t.classification == "sensitive_object"
        } | {c.target for c in snapshot.expected_access if c.relationship == "object_read"}
        self.declared_reads: dict[str, set[str]] = defaultdict(set)
        for fact in snapshot.facts.values():
            if fact.predicate == "s3_get_object":
                self.declared_reads[fact.subject].add(fact.object)
        # Memo keys: every value a prerequisite copies from a fact or a node.
        self.fact_keys = {triple: (f.id, f.state, f.pointer) for triple, f in snapshot.fact_index.items()}
        self.node_keys = {node_id: (n.account_id, n.pointer) for node_id, n in snapshot.nodes.items()}

    def objects_for(self, subject: str) -> list[str]:
        """Rule A objects: protected or expected-access objects, plus those the subject has a read fact for."""
        return sorted(self.objects | self.declared_reads.get(subject, set()))

    def s3_key(self, subject: str, objects: list[str]) -> tuple:
        get = self.fact_keys.get
        return (subject, self.policy, tuple((obj, get(("s3_get_object", subject, obj))) for obj in objects))

    def context_key(self, subject: str) -> tuple:
        get = self.fact_keys.get
        return (
            subject,
            self.node_keys.get(subject),
            self.policy,
            tuple(
                (
                    workload,
                    self.node_keys[workload],
                    get(("lambda_create_function", subject, workload)),
                    get(("lambda_invoke_function", subject, workload)),
                    get(("controls_workload_code", subject, workload)),
                )
                for workload in self.workloads
            ),
        )

    def row_key(self, subject: str, role: str) -> tuple:
        get = self.fact_keys.get
        return (
            role,
            self.node_keys[role],
            get(("iam_pass_role_to_lambda", subject, role)),
            get(("role_trusts_lambda_service", role, None)),
        )


class _S3Part:
    """A subject's Rule A candidates, one per object in objects_for order."""

    __slots__ = ("pairs", "issues", "counts", "established", "possible")

    def __init__(self, inputs: _Inputs, subject: str, objects: list[str]) -> None:
        candidates = [_s3_candidate(inputs.snapshot, subject, obj, inputs.policy) for obj in objects]
        self.pairs = [(c.id, c) for c in candidates]
        # Object order is candidate-ID order within one subject.
        self.issues = [_unresolved_issue(c) for c in candidates if c.state == UNKNOWN]
        self.counts = [0, 0, 0]
        for c in candidates:
            self.counts[_rank(c.state)] += 1
        self.established = [(c.target, c) for c in candidates if c.state == TRUE]
        self.possible = [(c.target, c) for c in candidates if c.state != FALSE]


class _Context:
    """What every Rule B candidate of one subject shares: its node, the policy and each workload's facts."""

    __slots__ = ("account", "account_pointer", "columns", "rows")

    def __init__(self, inputs: _Inputs, subject: str) -> None:
        snapshot = inputs.snapshot
        node = snapshot.nodes[subject]
        self.account = node.account_id
        self.account_pointer = f"{node.pointer}/account_id"
        self.columns = []
        for workload in inputs.workloads:
            w_node = snapshot.nodes[workload]
            create = _fact_prerequisite(snapshot, "lambda_create_function", subject, workload)
            invoke = _fact_prerequisite(snapshot, "lambda_invoke_function", subject, workload)
            controls = _fact_prerequisite(snapshot, "controls_workload_code", subject, workload)
            rank = min(_rank(create.state), _rank(invoke.state), _rank(controls.state))
            self.columns.append(
                (
                    workload,
                    w_node.account_id,
                    f"{w_node.pointer}/account_id",
                    create,
                    invoke,
                    controls,
                    rank,
                    _unknown((create, invoke, controls)),
                )
            )
        self.rows: dict[tuple, _Row] = {}


class _Row:
    """The Rule B candidates from one subject to one role, one per workload in workload order.

    Within a row, workload order is candidate-ID order, so the coverage issues
    are kept in that order. An issue lists the unknown prerequisites in
    prerequisite order: pass role, the workload's three, trust, same account,
    policy. The shared ones are worked out once per row or per workload.
    """

    __slots__ = ("pairs", "issues", "counts", "_best")

    def __init__(self, inputs: _Inputs, context: _Context, subject: str, role: str) -> None:
        snapshot = inputs.snapshot
        policy = inputs.policy
        passed = _fact_prerequisite(snapshot, "iam_pass_role_to_lambda", subject, role)
        trusted = _fact_prerequisite(snapshot, "role_trusts_lambda_service", role, None)
        r_node = snapshot.nodes[role]
        account, s_pointer = context.account, context.account_pointer
        r_account, r_pointer = r_node.account_id, f"{r_node.pointer}/account_id"
        head = min(_rank(passed.state), _rank(trusted.state), _rank(policy.state))
        (pass_reasons, pass_pointers), (trust_reasons, trust_pointers) = _unknown((passed,)), _unknown((trusted,))
        policy_reasons, policy_pointers = inputs.policy_unknown
        self.pairs: list[tuple[str, Candidate]] = []
        self.issues: list[CoverageIssue] = []
        self.counts = [0, 0, 0]
        for workload, w_account, w_pointer, create, invoke, controls, rank, (w_reasons, w_pointers) in context.columns:
            same = _same_account_prerequisite(
                subject, role, workload, account == r_account == w_account, (s_pointer, r_pointer, w_pointer)
            )
            state = min(head, rank, _rank(same.state))
            candidate = Candidate(
                f"B:{subject}->{role}@{workload}",
                RULE_LAMBDA,
                subject,
                role,
                workload,
                (passed, create, invoke, controls, trusted, same, policy),
                _STATES[state],
            )
            self.pairs.append((candidate.id, candidate))
            self.counts[state] += 1
            if state == 1:
                same_reasons, same_pointers = ((same.unresolved_reason(),), same.pointers) if same.state == UNKNOWN else ((), ())
                self.issues.append(
                    _issue(
                        candidate,
                        pass_reasons + w_reasons + trust_reasons + same_reasons + policy_reasons,
                        pass_pointers + w_pointers + trust_pointers + same_pointers + policy_pointers,
                    )
                )
        self._best: dict[bool, Candidate] = {}

    def reaches(self, established: bool) -> bool:
        """Whether the row has an edge in the established graph (true) or the full graph (not false)."""
        return self.counts[2] > 0 if established else self.counts[1] + self.counts[2] > 0

    def best(self, established: bool) -> Candidate:
        """The edge a witness takes to this role: the lowest sort key among the row's edges."""
        if established not in self._best:
            edges = [c for _, c in self.pairs if (c.state == TRUE if established else c.state != FALSE)]
            self._best[established] = min(edges, key=lambda c: c.sort_key)
        return self._best[established]


class _Subject:
    """One evaluated subject's candidates: Rule A, then one Rule B row per other role, in role order."""

    __slots__ = ("s3", "rows")

    def __init__(self, inputs: _Inputs, memo: _Memo, subject: str) -> None:
        objects = inputs.objects_for(subject)
        key = inputs.s3_key(subject, objects)
        s3 = memo.s3.get(key)
        if s3 is None:
            s3 = memo.s3[key] = _S3Part(inputs, subject, objects)
        self.s3 = s3
        self.rows: dict[str, _Row] = {}
        roles = [role for role in inputs.roles if role != subject]
        if not roles:
            return
        context_key = inputs.context_key(subject)
        context = memo.contexts.get(context_key)
        if context is None:
            context = memo.contexts[context_key] = _Context(inputs, subject)
        for role in roles:
            row_key = inputs.row_key(subject, role)
            row = context.rows.get(row_key)
            if row is None:
                row = context.rows[row_key] = _Row(inputs, context, subject, role)
            self.rows[role] = row


def _generate(inputs: _Inputs, memo: _Memo) -> dict[str, _Subject]:
    """Evaluate every candidate from subjects that are, or may be, reachable.

    Rule A covers S3 objects that are protected or named in an expected-access
    check, plus any object the subject has a declared s3_get_object fact for.
    Rule B covers every other role through every represented Lambda workload.
    Missing prerequisites are unknown, so an undeclared relationship from a
    reachable subject makes coverage incomplete rather than silently safe.
    Subjects are evaluated breadth first from the entry principals, in sorted
    order; a role is queued, once, the first time a candidate to it is not
    false.
    """
    subjects: dict[str, _Subject] = {}
    queue = deque(sorted(inputs.snapshot.entry_principals))
    queued = set(queue)
    while queue:
        subject = queue.popleft()
        if subject in subjects:
            continue
        evaluated = subjects[subject] = _Subject(inputs, memo, subject)
        for role, row in evaluated.rows.items():
            if role not in queued and row.reaches(established=False):
                queued.add(role)
                queue.append(role)
    return subjects


def _witnesses(subjects: dict[str, _Subject], source: str, established: bool) -> dict[str, tuple[Candidate, ...]]:
    """Shortest witness to every reachable node, ties broken by fact IDs.

    Layered BFS with a visited set: each node is settled at its first layer,
    so cycles terminate and all simple paths are never enumerated. A path's key
    is its candidates' sort keys in order, and the witness to a node is the
    lowest-key extension of a witness one layer up. Keys of one layer are
    distinct, so each layer is ordered by key once: by the rank of the parent,
    then the sort key of the last step. The first parent in that order to
    reach a node gives it its witness, through its lowest-key edge there.
    """
    best: dict[str, tuple[Candidate, ...]] = {source: ()}
    layer = [source]
    while layer:
        reached: dict[str, tuple[int, Candidate]] = {}
        for rank, node in enumerate(layer):
            subject = subjects.get(node)
            if subject is None:
                continue
            for target, candidate in subject.s3.established if established else subject.s3.possible:
                if target not in best and target not in reached:
                    reached[target] = (rank, candidate)
            for target, row in subject.rows.items():
                if target not in best and target not in reached and row.reaches(established):
                    reached[target] = (rank, row.best(established))
        order = sorted(reached, key=lambda node: (reached[node][0], reached[node][1].sort_key))
        for node in order:
            rank, candidate = reached[node]
            best[node] = best[layer[rank]] + (candidate,)
        layer = order
    return best


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


def _coverage(inputs: _Inputs, subjects: dict[str, _Subject]) -> Coverage:
    snapshot = inputs.snapshot
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
    # Unresolved candidates in candidate-ID order, without sorting the IDs. An ID is
    # "A:<subject>-><object>" or "B:<subject>-><role>@<workload>", and IDs never contain
    # '>' or '@', so every A sorts before every B, subjects sort as "<subject>->",
    # roles as "<role>@", and objects and workloads as themselves.
    by_subject = sorted(subjects, key=lambda subject: subject + "->")
    by_role = sorted(inputs.roles, key=lambda role: role + "@")
    for subject in by_subject:
        issues.extend(subjects[subject].s3.issues)
    for subject in by_subject:
        rows = subjects[subject].rows
        for role in by_role:
            row = rows.get(role)
            if row is not None:
                issues.extend(row.issues)

    s3, lam = [0, 0, 0], [0, 0, 0]
    for evaluated in subjects.values():
        for i, n in enumerate(evaluated.s3.counts):
            s3[i] += n
        for row in evaluated.rows.values():
            for i, n in enumerate(row.counts):
                lam[i] += n
    notes = [
        "Candidates are evaluated for every subject that is reachable, or possibly reachable, from an entry principal.",
        "Rule A evaluates S3 objects that are protected or named in an expected-access check, plus objects with a declared s3_get_object fact.",
    ]
    if not inputs.workloads:
        notes.append("No Lambda workload is represented, so Rule B has no candidates.")
    return Coverage(
        complete=not issues,
        issues=tuple(issues),
        candidate_counts={rule: {TRUE: c[2], FALSE: c[0], UNKNOWN: c[1]} for rule, c in ((RULE_S3, s3), (RULE_LAMBDA, lam))},
        subjects_evaluated=tuple(sorted(subjects)),
        notes=tuple(notes),
    )


def _expected(check: ExpectedAccess, definite: dict, possible: dict) -> ExpectedAccessResult:
    if check.target in definite:
        return ExpectedAccessResult(check, "pass", definite[check.target])
    if check.target in possible:
        return ExpectedAccessResult(check, "inconclusive", possible[check.target])
    return ExpectedAccessResult(check, "fail", ())


def analyze(snapshot: Snapshot, reuse: SnapshotAnalysis | None = None) -> SnapshotAnalysis:
    """Analyse a snapshot; with reuse, candidates whose inputs match that analysis's are taken from it."""
    memo = reuse._memo if reuse is not None else _Memo()
    inputs = _Inputs(snapshot)
    subjects = _generate(inputs, memo)
    candidates: dict[str, Candidate] = {}
    for evaluated in subjects.values():
        candidates.update(evaluated.s3.pairs)
        for row in evaluated.rows.values():
            candidates.update(row.pairs)

    findings: dict[str, Finding] = {}
    potential: dict[str, PotentialFinding] = {}
    definite_by_entry: dict[str, dict] = {}
    possible_by_entry: dict[str, dict] = {}
    for entry in sorted(snapshot.entry_principals):
        definite = definite_by_entry[entry] = _witnesses(subjects, entry, established=True)
        possible = possible_by_entry[entry] = _witnesses(subjects, entry, established=False)
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
        coverage=_coverage(inputs, subjects),
        _memo=memo,
    )
