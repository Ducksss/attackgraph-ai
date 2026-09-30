"""Run the live engine and the frozen oracle (tests/reference) on the same input and diff the results.

Everything the pipeline returns is compared, field by field as the oracle's
dataclasses define their fields: both loaded files, every analysis (the
baseline, the proposal and each simulated fix) with its candidates, graph,
findings, witnesses, expected-access results and coverage, the comparison
with its deltas and changes, and the fix candidates with their ranking. So
are the public functions built on them and the Markdown report.

Run as a script, it checks one of the adversarial worst cases in this process
and prints the differences as JSON; tests/test_differential.py runs those in
parallel worker processes because the oracle takes several seconds on each.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import random
import sys
import time
from operator import attrgetter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tests", ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import networkx as nx  # noqa: E402
from reference import analysis_v1, compare_v1, pipeline_v1, report_v1, simulate_v1  # noqa: E402

import benchmark  # noqa: E402  (scripts/benchmark.py: the worst-case generator)
from attackgraph import pipeline, report, simulate  # noqa: E402
from attackgraph import snapshot as snapshot_module  # noqa: E402
from attackgraph.snapshot import POLICY_CONTROLS, PREDICATES, UNMODELLED_MECHANISMS, load_snapshot  # noqa: E402

GENERATED_AT = "2026-10-01T00:00:00Z"
WORST_CASES = {
    "passrole-49x49": benchmark.CASES["passrole-49x49"],
    "passrole-66x33": benchmark.CASES["passrole-66x33"],
}


def _oracle_fields() -> dict[str, tuple[str, ...]]:
    """Field names of every dataclass the oracle's results are made of, by class name."""
    fields: dict[str, tuple[str, ...]] = {}
    for module in (analysis_v1, compare_v1, simulate_v1, pipeline_v1, snapshot_module):
        for value in vars(module).values():
            if isinstance(value, type) and dataclasses.is_dataclass(value):
                fields.setdefault(value.__name__, tuple(f.name for f in dataclasses.fields(value)))
    return fields


FIELDS = _oracle_fields()
# Classes whose fields hold only strings, numbers, booleans, None or tuples of them,
# so a tuple of their field values compares by value. A nested object would make the
# tuples unequal (instances of the two engines' classes never compare equal), so a
# wrong entry here can only fail the comparison, never hide a difference.
FLAT = ("Prerequisite", "CoverageIssue", "ConfigChange", "Issue", "Node", "Fact", "ProtectedTarget", "ExpectedAccess", "Revision")
_VALUES = {name: attrgetter(*FIELDS[name]) for name in FLAT}
_CANDIDATE = attrgetter(*(f for f in FIELDS["Candidate"] if f != "prerequisites"))
_PREREQUISITE = _VALUES["Prerequisite"]
_PRIMITIVES = (str, int, float, bool, type(None))


def _candidate_values(candidate) -> tuple:
    return _CANDIDATE(candidate), tuple(map(_PREREQUISITE, candidate.prerequisites))


def _path(path) -> str:
    """Paths are built lazily, as (parent, ".attribute") or (parent, [key]) pairs, and spelled out only for a difference."""
    if isinstance(path, str):
        return path
    parent, step = path
    return f"{_path(parent)}{step}" if isinstance(step, str) else f"{_path(parent)}[{step[0]!r}]"


class Differences:
    """Walks two results in parallel and records where they differ, at most `limit` places."""

    def __init__(self, limit: int = 10) -> None:
        self.found: list[str] = []
        self.limit = limit
        self._compared: set[tuple[int, int]] = set()
        self._keep: list = []

    def fail(self, path, detail: str) -> None:
        if len(self.found) < self.limit:
            self.found.append(f"{_path(path)}: {detail}"[:600])

    def __call__(self, old, new, path) -> None:
        if len(self.found) >= self.limit:
            return
        name = type(old).__name__
        if name != type(new).__name__:
            return self.fail(path, f"{name} != {type(new).__name__}")
        if isinstance(old, _PRIMITIVES):
            if old != new:
                self.fail(path, f"{old!r} != {new!r}")
        elif name in _VALUES:
            a, b = _VALUES[name](old), _VALUES[name](new)
            if a != b:
                self.fail(path, f"{a!r} != {b!r}")
        elif name == "Candidate":
            a, b = _candidate_values(old), _candidate_values(new)
            if a != b:
                self.fail(path, f"{a!r} != {b!r}")
        elif isinstance(old, (tuple, list)):
            if len(old) != len(new):
                self.fail(path, f"{len(old)} items != {len(new)} items")
            self._items(list(enumerate(old)), list(new), path)
        elif isinstance(old, dict):
            if list(old) != list(new):
                missing, extra = [k for k in old if k not in new][:3], [k for k in new if k not in old][:3]
                return self.fail(path, f"keys differ (only old: {missing}, only new: {extra}, or order)")
            self._items(list(old.items()), list(new.values()), path)
        elif isinstance(old, (set, frozenset)):
            if old != new:
                self.fail(path, f"only old {sorted(old - new)[:5]}, only new {sorted(new - old)[:5]}")
        elif dataclasses.is_dataclass(old):
            pair = (id(old), id(new))
            if pair in self._compared:
                return
            self._compared.add(pair)
            self._keep.append((old, new))  # the ids above stay valid while both are alive
            for field in FIELDS[name]:
                if name == "SnapshotAnalysis" and field == "graph":
                    self._graph(old, new, (path, ".graph"))
                else:
                    self(getattr(old, field), getattr(new, field), (path, f".{field}"))
        else:
            raise TypeError(f"{_path(path)}: no comparison for {name}")

    def _items(self, old_items: list, new_values: list, path) -> None:
        """Pairwise items; runs of candidates or flat records are compared in a tight loop."""
        if not old_items:
            return
        name = type(old_items[0][1]).__name__
        values = _candidate_values if name == "Candidate" else _VALUES.get(name)
        if values is None:
            for (key, a), b in zip(old_items, new_values):
                self(a, b, (path, [key]))
            return
        for (key, a), b in zip(old_items, new_values):
            if type(a).__name__ != name or type(b).__name__ != name or values(a) != values(b):
                self(a, b, (path, [key]))  # the full comparison reports the difference

    def _graph(self, old_analysis, new_analysis, path) -> None:
        """Same nodes and edges in the same order, each edge's data being exactly {"candidate": c}.

        c must be the very object its analysis lists under that key in .candidates,
        which is compared field by field, so it is not compared a second time here.
        """
        old, new = old_analysis.graph, new_analysis.graph
        if not (isinstance(old, nx.MultiDiGraph) and isinstance(new, nx.MultiDiGraph)):
            return self.fail(path, "not a MultiDiGraph")
        if list(old.nodes) != list(new.nodes):
            return self.fail((path, ".nodes"), "differ")
        old_edges, new_edges = list(old.edges(keys=True, data=True)), list(new.edges(keys=True, data=True))
        if [e[:3] for e in old_edges] != [e[:3] for e in new_edges]:
            return self.fail((path, ".edges"), "differ in endpoints, keys or order")
        for analysis, edges in ((old_analysis, old_edges), (new_analysis, new_edges)):
            get = analysis.candidates.get
            for u, v, key, data in edges:
                candidate = get(key)
                if candidate is None or data.get("candidate") is not candidate or len(data) != 1 or u != candidate.subject or v != candidate.target:
                    return self.fail((path, f".edges[{key!r}]"), "edge data is not the analysis's candidate for that key")


def _analyses(result) -> list[tuple[str, object]]:
    comparison = result.comparison
    out = [("baseline", comparison.baseline), ("proposal", comparison.proposal)]
    return out + [(f"fixes[{i}].simulated", fix.simulated) for i, fix in enumerate(result.fixes)]


def differences(old, new, limit: int = 10, slow_oracle_calls: bool = True) -> list[str]:
    """Where two pipeline results differ; empty when they are identical.

    slow_oracle_calls=False skips what takes the oracle seconds on the worst
    cases and is derived from compared fields anyway: calling its
    participating_fact_ids and eligible_grants again (their results feed the
    compared fix candidates and untested count), and walking its established
    graph view (a filter of the compared graph).
    """
    diff = Differences(limit)
    diff(old, new, "result")
    diff(old.ok, new.ok, "result.ok")
    if old.comparison is None or new.comparison is None:
        return diff.found
    oc, nc = old.comparison, new.comparison
    for attr in ("complete", "verdict", "changed_fact_ids"):
        diff(getattr(oc, attr), getattr(nc, attr), f"comparison.{attr}")
    for status in ("added", "removed", "unchanged", "inconclusive"):
        diff(oc.count(status), nc.count(status), f"comparison.count({status!r})")
    for (label, a), (_, b) in zip(_analyses(old), _analyses(new)):
        diff(a.high_risk_count, b.high_risk_count, f"{label}.high_risk_count")
        if slow_oracle_calls:
            diff(list(a.established_graph.edges(keys=True)), list(b.established_graph.edges(keys=True)), f"{label}.established_graph")
    for i, (a, b) in enumerate(zip(old.fixes, new.fixes)):
        for attr in ("coverage_complete", "failed_expected", "expected_changes", "expected_after"):
            diff(getattr(a, attr), getattr(b, attr), f"fixes[{i}].{attr}")
        diff(a.describe(), b.describe(), f"fixes[{i}].describe()")
    for d in oc.deltas:
        best_old, best_new = simulate_v1.best_fix_for(old.fixes, d.id), simulate.best_fix_for(new.fixes, d.id)
        diff(getattr(best_old, "id", None), getattr(best_new, "id", None), f"best_fix_for({d.id!r})")
    if slow_oracle_calls:
        diff(simulate_v1.participating_fact_ids(oc.proposal), simulate.participating_fact_ids(nc.proposal), "participating_fact_ids")
        diff(simulate_v1.eligible_grants(oc), simulate.eligible_grants(nc), "eligible_grants")
    for i, (sim_old, sim_new) in enumerate([(None, None), *zip(old.fixes, new.fixes)]):
        before = report_v1.build_report(oc, old.fixes, sim_old, generated_at=GENERATED_AT)
        after = report.build_report(nc, new.fixes, sim_new, generated_at=GENERATED_AT)
        if before != after:
            line = next(n for n, (x, y) in enumerate(zip(before.splitlines() + [""], after.splitlines() + [""])) if x != y)
            diff.fail(f"report(simulation={i - 1 if i else None})", f"line {line + 1} differs")
    return diff.found


def run_both(baseline: bytes, baseline_name: str, proposal: bytes, proposal_name: str):
    """The oracle's and the live engine's pipeline results for one pair of files."""
    old = pipeline_v1.run(baseline, baseline_name, proposal, proposal_name)
    new = pipeline.run(baseline, baseline_name, proposal, proposal_name)
    return old, new


def run_both_loaded(baseline, proposal):
    """The same from already-loaded files. Loading is shared code, outside the engines compared."""
    return pipeline_v1.run_loaded(baseline, proposal), pipeline.run_loaded(baseline, proposal)


def fixture_files() -> list[Path]:
    """Every bundled snapshot file: the demo fixtures, the examples (two of them invalid) and snapshots/."""
    return sorted(p for folder in ("fixtures/demo", "fixtures/examples", "snapshots") for p in (ROOT / folder).glob("*.json"))


# ---------------------------------------------------------------------------
# Seeded random pairs


def _ids(rng: random.Random, count: int, tricky: bool) -> list[str]:
    """Unique node IDs. Tricky ones are often prefixes of each other, joined by '-', '.', '_' or digits,
    which is exactly where candidate-ID order ("<subject>->", "<role>@") departs from plain ID order."""
    if not tricky:
        width = rng.choice((1, 2))
        return [f"n{i:0{width}d}" if rng.random() < 0.5 else f"n{i}" for i in range(count)] if count else []
    ids: list[str] = []
    seen: set[str] = set()
    suffixes = ("-", ".", "_", "0", "1", "9", "a", "z", "-0", "--", "-a", ".1", "_-", "0-")
    while len(ids) < count:
        parent = rng.choice(ids) if ids and rng.random() < 0.75 else rng.choice(("x", "y", "x0"))
        node_id = (parent + rng.choice(suffixes))[:64]
        if node_id not in seen:
            seen.add(node_id)
            ids.append(node_id)
    return ids


_PROFILES = {
    # name: (weight, node range, cap on roles x functions, fact range)
    "tiny": (35, (2, 10), 16, (0, 30)),
    "small": (35, (8, 30), 60, (10, 120)),
    "medium": (20, (25, 70), 120, (60, 300)),
    "large": (10, (70, 100), 200, (150, 300)),
}


def random_doc(rng: random.Random, snapshot_id: str) -> dict:
    profile = rng.choices(list(_PROFILES), weights=[p[0] for p in _PROFILES.values()])[0]
    _, (lo, hi), cap, (f_lo, f_hi) = _PROFILES[profile]
    total = rng.randint(lo, hi)
    while True:
        roles, functions = rng.randint(0, total // 2), rng.randint(0, total // 3)
        if roles * functions <= cap:
            break
    principals = rng.randint(1, max(1, min(25, total - roles - functions)))
    objects = max(0, total - roles - functions - principals)
    kinds = ["principal"] * principals + ["role"] * roles + ["lambda"] * functions + ["s3_object"] * objects
    rng.shuffle(kinds)
    ids = _ids(rng, len(kinds), tricky=rng.random() < 0.5)
    accounts = rng.choice((["syn-a"], ["syn-a"], ["syn-a", "syn-b"], ["syn-a", "syn-b", "syn-c-1"]))
    cross = rng.choice((0.0, 0.05, 0.2, 0.5))
    nodes = [
        {
            "id": node_id,
            "kind": kind,
            "label": rng.choice((node_id, f"Node {node_id}", "Admin **role** <b>", "a|b`c", "Überprüfung")),
            "account_id": rng.choice(accounts) if rng.random() < cross else accounts[0],
        }
        for node_id, kind in zip(ids, kinds)
    ]
    by_kind: dict[str, list[str]] = {k: [n["id"] for n in nodes if n["kind"] == k] for k in ("principal", "role", "lambda", "s3_object")}

    weights = rng.choice(((6, 3, 1), (2, 7, 1), (3, 3, 4), (5, 5, 0), (9, 1, 0)))
    facts: list[dict] = []
    triples: set[tuple] = set()

    def add(predicate: str, subject: str, obj: str | None, state: str | None = None) -> None:
        if (predicate, subject, obj) in triples or len(facts) >= 300:
            return
        triples.add((predicate, subject, obj))
        record = {"id": f"f{len(facts)}", "predicate": predicate, "subject": subject}
        if obj is not None:
            record["object"] = obj
        record["state"] = state or rng.choices(("true", "false", "unknown"), weights=weights)[0]
        facts.append(record)

    def pick(kinds_: tuple[str, ...]) -> str | None:
        pool = [node_id for kind in kinds_ for node_id in by_kind[kind]]
        return rng.choice(pool) if pool else None

    n_facts = rng.randint(f_lo, f_hi)
    # Routes: a subject that controls a function, a role that trusts Lambda, and the pass-role grant.
    for _ in range(rng.randint(0, 6)):
        subject, workload, role = pick(("principal", "role")), pick(("lambda",)), pick(("role",))
        if subject and workload and role and subject != role:
            for predicate in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code"):
                add(predicate, subject, workload, "true" if rng.random() < 0.8 else None)
            add("role_trusts_lambda_service", role, None, "true" if rng.random() < 0.8 else None)
            add("iam_pass_role_to_lambda", subject, role)
    attempts = 0
    while len(facts) < n_facts and attempts < 4 * n_facts + 20:
        attempts += 1
        predicate = rng.choice(sorted(PREDICATES))
        spec = PREDICATES[predicate]
        subject = pick(spec.subject_kinds)
        obj = pick(spec.object_kinds) if spec.object_kinds else None
        if subject is None or (spec.object_kinds and obj is None):
            continue
        add(predicate, subject, obj)
    rng.shuffle(facts)

    protected = [{"node": r, "classification": "privileged_role"} for r in by_kind["role"] if rng.random() < 0.4]
    protected += [{"node": o, "classification": "sensitive_object"} for o in by_kind["s3_object"] if rng.random() < 0.5]
    rng.shuffle(protected)
    entries = rng.sample(by_kind["principal"], rng.randint(1, min(20, len(by_kind["principal"]))))
    doc = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "synthetic": True,
        "model_version": "attackgraph-rules-v1",
        "coverage": {
            "policy_controls": {k: "unresolved" if rng.random() < 0.06 else "resolved" for k in POLICY_CONTROLS},
            "unmodelled_mechanisms": rng.sample(sorted(UNMODELLED_MECHANISMS), rng.choice((0, 0, 0, 0, 0, 0, 1, 2))),
        },
        "nodes": nodes,
        "facts": facts,
        "entry_principals": entries,
        "protected_targets": protected[:100],
        "expected_access": [],
    }
    _add_expected(rng, doc, rng.randint(0, 6))
    if rng.random() < 0.3:
        doc["name"] = rng.choice(("Random pair", "Name with `code` and *stars*"))
    return doc


def closed_doc(rng: random.Random, snapshot_id: str) -> dict:
    """A snapshot that declares every prerequisite a reachable subject needs, so coverage is complete.

    Only a few roles trust Lambda. Every subject has a pass-role fact for each
    of them and all three workload facts for every function, so no candidate
    from an evaluated subject is unknown, even after a grant is turned on.
    Rule A facts are declared for every relevant object. Some pass-role grants
    are true, including between roles, so witnesses can be chains.
    """
    total_roles, functions = rng.randint(1, 8), rng.randint(1, 4)
    principals, objects = rng.randint(1, 5), rng.randint(0, 4)
    kinds = ["principal"] * principals + ["role"] * total_roles + ["lambda"] * functions + ["s3_object"] * objects
    rng.shuffle(kinds)
    ids = _ids(rng, len(kinds), tricky=rng.random() < 0.5)
    nodes = [{"id": i, "kind": k, "label": f"Node {i}", "account_id": "syn-a"} for i, k in zip(ids, kinds)]
    by_kind = {k: [n["id"] for n in nodes if n["kind"] == k] for k in ("principal", "role", "lambda", "s3_object")}
    subjects = by_kind["principal"] + by_kind["role"]
    trusting = rng.sample(by_kind["role"], rng.randint(1, min(3, len(by_kind["role"]))))
    p_true = rng.choice((0.2, 0.4, 0.7))
    facts: list[dict] = []

    def add(predicate: str, subject: str, obj: str | None, state: str) -> None:
        record = {"id": f"c{len(facts)}", "predicate": predicate, "subject": subject}
        if obj is not None:
            record["object"] = obj
        record["state"] = state
        facts.append(record)

    def coin(p: float) -> str:
        return "true" if rng.random() < p else "false"

    for role in by_kind["role"]:
        add("role_trusts_lambda_service", role, None, "true" if role in trusting else coin(0.1))
    trusted = {f["subject"] for f in facts if f["state"] == "true"}
    for subject in subjects:
        for role in sorted(trusted):
            if role != subject:
                add("iam_pass_role_to_lambda", subject, role, coin(p_true))
        for workload in by_kind["lambda"]:
            for predicate in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code"):
                add(predicate, subject, workload, coin(0.8))
    protected = [{"node": r, "classification": "privileged_role"} for r in by_kind["role"] if rng.random() < 0.6]
    protected += [{"node": o, "classification": "sensitive_object"} for o in by_kind["s3_object"] if rng.random() < 0.6]
    entries = rng.sample(by_kind["principal"], rng.randint(1, len(by_kind["principal"])))
    doc = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "synthetic": True,
        "model_version": "attackgraph-rules-v1",
        "coverage": {"policy_controls": {k: "resolved" for k in POLICY_CONTROLS}, "unmodelled_mechanisms": []},
        "nodes": nodes,
        "facts": facts,
        "entry_principals": entries,
        "protected_targets": protected,
        "expected_access": [],
    }
    _add_expected(rng, doc, rng.randint(0, 3))
    relevant = {t["node"] for t in protected if t["classification"] == "sensitive_object"}
    relevant |= {c["target"] for c in doc["expected_access"] if c["relationship"] == "object_read"}
    for subject in subjects:
        for obj in sorted(relevant):
            add("s3_get_object", subject, obj, coin(0.3))
    rng.shuffle(facts)
    return doc


def _fact_ids(rng: random.Random, count: int) -> list[str]:
    """Unique fact IDs in random order, so witness ties are broken by IDs unrelated to file order."""
    ids: set[str] = set()
    while len(ids) < count:
        ids.add("".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789-._") for _ in range(rng.randint(1, 4))).lstrip("-._") or "f")
    out = sorted(ids)
    rng.shuffle(out)
    return out


def lattice_doc(rng: random.Random, snapshot_id: str) -> dict:
    """Layers of roles, each passing roles in the next through several functions, with some cycles.

    Several parents in one layer reach the same role through several functions,
    so witnesses depend on the tie-break by fact IDs, which are random tokens.
    When small enough, every other pass-role pair is declared false, so coverage
    is complete; some edges are unknown, so the full graph differs from the
    established one.
    """
    principals = [f"p{i}" for i in range(rng.randint(1, 3))]
    layers = [[f"r{k}-{i}" for i in range(rng.randint(1, 4))] for k in range(rng.randint(2, 4))]
    roles = [r for layer in layers for r in layer]
    workloads = [f"w{i}" for i in range(rng.randint(1, 3))]
    objects = [f"o{i}" for i in range(rng.randint(0, 2))]
    nodes = [{"id": n, "kind": k, "label": n, "account_id": "syn-a"} for k, group in (("principal", principals), ("role", roles), ("lambda", workloads), ("s3_object", objects)) for n in group]
    rows: list[tuple] = []
    tiers = [principals, *layers]
    subjects = principals + roles
    for subject in subjects:
        for workload in workloads:
            for predicate in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code"):
                rows.append((predicate, subject, workload, rng.choices(("true", "false", "unknown"), (8, 1, 1))[0]))
    edges = set()
    for k, tier in enumerate(tiers[:-1]):
        for subject in tier:
            for role in tiers[k + 1]:
                if rng.random() < 0.7:
                    edges.add((subject, role))
                    rows.append(("iam_pass_role_to_lambda", subject, role, rng.choices(("true", "false", "unknown"), (7, 2, 1))[0]))
    for role in roles:
        rows.append(("role_trusts_lambda_service", role, None, rng.choices(("true", "unknown"), (9, 1))[0]))
    for role in layers[-1]:  # back to the first layer: a cycle
        if rng.random() < 0.5:
            back = rng.choice(layers[0])
            if back != role and (role, back) not in edges:
                edges.add((role, back))
                rows.append(("iam_pass_role_to_lambda", role, back, "true"))
    others = [(s, r) for s in subjects for r in roles if s != r and (s, r) not in edges]
    if len(rows) + len(others) + len(subjects) * len(objects) <= 300:
        rows += [("iam_pass_role_to_lambda", s, r, "false") for s, r in others]
        rows += [("s3_get_object", s, o, rng.choice(("true", "false"))) for s in subjects for o in objects]
    fact_ids = _fact_ids(rng, len(rows))
    facts = []
    for fact_id, (predicate, subject, obj, state) in zip(fact_ids, rows):
        record = {"id": fact_id, "predicate": predicate, "subject": subject, "state": state}
        if obj is not None:
            record["object"] = obj
        facts.append(record)
    rng.shuffle(facts)
    protected = [{"node": r, "classification": "privileged_role"} for r in roles if rng.random() < 0.5]
    protected += [{"node": o, "classification": "sensitive_object"} for o in objects]
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "synthetic": True,
        "model_version": "attackgraph-rules-v1",
        "coverage": {"policy_controls": {k: "resolved" for k in POLICY_CONTROLS}, "unmodelled_mechanisms": []},
        "nodes": nodes,
        "facts": facts,
        "entry_principals": principals,
        "protected_targets": protected,
        "expected_access": [],
    }


def fan_out_pair(rng: random.Random) -> tuple[dict, dict]:
    """One principal gains iam:PassRole on 26 to 40 protected roles: more fixes than are simulated."""
    count = rng.randint(26, 40)
    roles = [f"r{i}" for i in range(count)]
    nodes = [{"id": "p0", "kind": "principal", "label": "p0", "account_id": "syn-a"}, {"id": "l0", "kind": "lambda", "label": "l0", "account_id": "syn-a"}]
    nodes += [{"id": r, "kind": "role", "label": r, "account_id": "syn-a"} for r in roles]
    facts = [{"id": f"w-{p}", "predicate": p, "subject": "p0", "object": "l0", "state": "true"} for p in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code")]
    facts += [{"id": f"t-{r}", "predicate": "role_trusts_lambda_service", "subject": r, "state": "true"} for r in roles]
    facts += [{"id": f"pass-{r}", "predicate": "iam_pass_role_to_lambda", "subject": "p0", "object": r, "state": "false"} for r in roles]
    if rng.random() < 0.5:  # roles cannot create the function: complete coverage
        facts += [{"id": f"c-{r}", "predicate": "lambda_create_function", "subject": r, "object": "l0", "state": "false"} for r in roles]
    rng.shuffle(facts)
    baseline = {
        "schema_version": "1.0",
        "snapshot_id": "baseline",
        "synthetic": True,
        "model_version": "attackgraph-rules-v1",
        "coverage": {"policy_controls": {k: "resolved" for k in POLICY_CONTROLS}, "unmodelled_mechanisms": []},
        "nodes": nodes,
        "facts": facts,
        "entry_principals": ["p0"],
        "protected_targets": [{"node": r, "classification": "privileged_role"} for r in roles if rng.random() < 0.9],
        "expected_access": [],
    }
    proposal = copy.deepcopy(baseline)
    proposal["snapshot_id"] = "proposal"
    for fact in proposal["facts"]:
        if fact["id"].startswith("pass-") and rng.random() < 0.9:
            fact["state"] = "true"
    return baseline, proposal


def _add_expected(rng: random.Random, doc: dict, count: int) -> None:
    kinds = {n["id"]: n["kind"] for n in doc["nodes"]}
    protected = {t["node"] for t in doc["protected_targets"]}
    open_targets = [n for n, k in kinds.items() if k in ("role", "s3_object") and n not in protected]
    used = {c["id"] for c in doc["expected_access"]}
    for _ in range(count):
        if not open_targets or len(doc["expected_access"]) >= 50:
            return
        target = rng.choice(open_targets)
        check_id = f"ea-{len(used)}-{rng.randint(0, 999)}"
        if check_id in used:
            continue
        used.add(check_id)
        relationship = "role_use" if kinds[target] == "role" else "object_read"
        doc["expected_access"].append(
            {"id": check_id, "principal": rng.choice(doc["entry_principals"]), "target": target, "relationship": relationship}
        )


def _mutate(rng: random.Random, doc: dict, closed: bool = False) -> dict:
    """A proposal derived from the baseline by a few random edits of every kind the comparison reports.

    Edits to a closed baseline are mostly grants turned on or off, which keep coverage complete.
    Some edits change one input of the engine's memo keys and nothing else: the account of a
    function or of a subject, a node's position (so its JSON pointer) or a fact's ID.
    """
    doc = copy.deepcopy(doc)
    doc["snapshot_id"] = "proposal"
    kinds = {n["id"]: n["kind"] for n in doc["nodes"]}
    edits = rng.choice((0, 1, 1, 2, 3, 4, 6, 10))
    for _ in range(edits):
        edit = rng.choices(
            ("enable", "flip", "enable_many", "remove", "add", "redefine", "account", "label", "shuffle", "policy",
             "mechanism", "entry", "target", "expected", "node", "workload_account", "subject_account", "move_node",
             "swap_nodes", "rename_fact"),
            weights=(
                (60, 20, 3, 1, 1, 1, 1, 3, 4, 1, 1, 3, 1, 3, 1, 2, 2, 2, 3, 2)
                if closed
                else (30, 15, 3, 6, 8, 4, 5, 3, 4, 3, 2, 3, 4, 3, 3, 4, 4, 3, 4, 3)
            ),
        )[0]
        facts = doc["facts"]
        workloads = [n for n in doc["nodes"] if n["kind"] == "lambda"]
        subjects = [n for n in doc["nodes"] if n["kind"] in ("principal", "role")]
        if edit in ("workload_account", "subject_account") and (workloads if edit == "workload_account" else subjects):
            node = rng.choice(workloads if edit == "workload_account" else subjects)
            node["account_id"] = "syn-b" if node["account_id"] != "syn-b" else "syn-a"
        elif edit == "move_node":
            doc["nodes"].insert(rng.randrange(len(doc["nodes"])), doc["nodes"].pop(rng.randrange(len(doc["nodes"]))))
        elif edit == "swap_nodes":
            # Two neighbours, neither a function: their pointers change and every function's stays.
            nodes = doc["nodes"]
            pairs = [i for i in range(len(nodes) - 1) if "lambda" not in (nodes[i]["kind"], nodes[i + 1]["kind"])]
            if pairs:
                i = rng.choice(pairs)
                nodes[i], nodes[i + 1] = nodes[i + 1], nodes[i]
        elif edit == "rename_fact" and facts:
            rng.choice(facts)["id"] = f"renamed-{rng.randint(0, 10**6)}"
        elif edit in ("enable", "flip") and facts:
            fact = rng.choice(facts)
            if edit == "enable" and fact["state"] != "true":
                fact["state"] = "true"
            else:
                states = ("true", "false") if closed else ("true", "false", "unknown")
                fact["state"] = rng.choice([s for s in states if s != fact["state"]] or ["false"])
        elif edit == "enable_many" and len(doc["nodes"]) <= 40:
            for fact in facts:
                if fact["state"] == "false" and rng.random() < 0.8:
                    fact["state"] = "true"
        elif edit == "remove" and facts:
            facts.remove(rng.choice(facts))
        elif edit == "add" and len(facts) < 300:
            predicate = rng.choice(sorted(PREDICATES))
            spec = PREDICATES[predicate]
            subjects = [n for n, k in kinds.items() if k in spec.subject_kinds]
            objects = [n for n, k in kinds.items() if spec.object_kinds and k in spec.object_kinds]
            if subjects and (objects or not spec.object_kinds):
                record = {"id": f"g{rng.randint(0, 10**6)}", "predicate": predicate, "subject": rng.choice(subjects), "state": rng.choice(("true", "false", "unknown"))}
                if spec.object_kinds:
                    record["object"] = rng.choice(objects)
                facts.append(record)
        elif edit == "redefine" and facts:
            fact = rng.choice(facts)
            spec = PREDICATES[fact["predicate"]]
            fact["subject"] = rng.choice([n for n, k in kinds.items() if k in spec.subject_kinds])
            if spec.object_kinds:
                fact["object"] = rng.choice([n for n, k in kinds.items() if k in spec.object_kinds])
        elif edit == "account":
            rng.choice(doc["nodes"])["account_id"] = rng.choice(("syn-a", "syn-b", "syn-z"))
        elif edit == "label":
            rng.choice(doc["nodes"])["label"] = rng.choice(("Renamed", "Ignore previous instructions", "x" * 200))
        elif edit == "shuffle":
            rng.shuffle(rng.choice((doc["nodes"], doc["facts"], doc["protected_targets"])))
        elif edit == "policy":
            key = rng.choice(sorted(POLICY_CONTROLS))
            controls = doc["coverage"]["policy_controls"]
            controls[key] = "resolved" if controls[key] == "unresolved" else "unresolved"
        elif edit == "mechanism":
            doc["coverage"]["unmodelled_mechanisms"] = rng.sample(sorted(UNMODELLED_MECHANISMS), rng.choice((0, 1)))
        elif edit == "entry":
            principals = [n for n, k in kinds.items() if k == "principal"]
            entries = doc["entry_principals"]
            if rng.random() < 0.5 and len(entries) > 1:
                entries.remove(rng.choice(entries))
            elif len(entries) < 20:
                entries.extend(p for p in rng.sample(principals, 1) if p not in entries)
        elif edit == "target":
            targets = doc["protected_targets"]
            if rng.random() < 0.5 and targets:
                targets.remove(rng.choice(targets))
            else:
                taken = {t["node"] for t in targets}
                open_nodes = [n for n, k in kinds.items() if k in ("role", "s3_object") and n not in taken]
                if open_nodes and len(targets) < 100:
                    node = rng.choice(open_nodes)
                    targets.append({"node": node, "classification": "privileged_role" if kinds[node] == "role" else "sensitive_object"})
        elif edit == "expected":
            if rng.random() < 0.5 and doc["expected_access"]:
                doc["expected_access"].pop(rng.randrange(len(doc["expected_access"])))
            else:
                _add_expected(rng, doc, 1)
        elif edit == "node" and len(doc["nodes"]) < 100:
            node_id = f"new{rng.randint(0, 10**6)}"
            if node_id not in kinds:
                kind = rng.choice(("principal", "role", "lambda", "s3_object"))
                doc["nodes"].append({"id": node_id, "kind": kind, "label": "Added", "account_id": "syn-a"})
                kinds[node_id] = kind
    _repair(doc)
    return doc


def _repair(doc: dict) -> None:
    """Drop whatever the edits made invalid: duplicate triples or IDs, and checks that no longer hold."""
    seen_ids, seen_triples, facts = set(), set(), []
    for fact in doc["facts"]:
        triple = (fact["predicate"], fact["subject"], fact.get("object"))
        if fact["id"] in seen_ids or triple in seen_triples:
            continue
        seen_ids.add(fact["id"])
        seen_triples.add(triple)
        facts.append(fact)
    doc["facts"] = facts[:300]
    entries = set(doc["entry_principals"])
    protected = {t["node"] for t in doc["protected_targets"]}
    doc["expected_access"] = [c for c in doc["expected_access"] if c["principal"] in entries and c["target"] not in protected]


def random_pair(seed: int):
    """A valid baseline and proposal, loaded. Most proposals are edits of the baseline; some are unrelated.

    Half the baselines are closed (complete coverage), so fixes are ranked and
    verified; the others leave facts undeclared, unknown or cross-account.
    """
    rng = random.Random(seed)
    kind = rng.choices(("closed", "open", "lattice", "fan-out"), weights=(40, 40, 17, 3))[0]
    if kind == "fan-out":
        baseline, proposal = fan_out_pair(rng)
    else:
        make = {"closed": closed_doc, "open": random_doc, "lattice": lattice_doc}[kind]
        baseline = make(rng, "baseline")
        proposal = make(rng, "proposal") if rng.random() < 0.08 else _mutate(rng, baseline, closed=kind != "open")
    names = ("baseline.json", "proposal.json")
    loaded = [load_snapshot(json.dumps(doc, indent=rng.choice((None, 1))).encode(), name) for doc, name in zip((baseline, proposal), names)]
    for result in loaded:
        assert result.ok, (seed, [str(i) for i in result.issues[:3]])
    return loaded


def main(argv: list[str]) -> int:
    """Worker mode: diff the oracle and the live engine on one worst case; print JSON."""
    case = argv[0]
    baseline, proposal = WORST_CASES[case]()
    started = time.perf_counter()
    old = pipeline_v1.run(baseline, "baseline.json", proposal, "proposal.json")
    middle = time.perf_counter()
    new = pipeline.run(baseline, "baseline.json", proposal, "proposal.json")
    done = time.perf_counter()
    found = differences(old, new, slow_oracle_calls=False)
    print(json.dumps({"case": case, "differences": found, "oracle_s": middle - started, "engine_s": done - middle,
                      "candidates": len(new.comparison.proposal.candidates), "fixes": len(new.fixes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
