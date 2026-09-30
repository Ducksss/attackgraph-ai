"""Time comparison plus fix simulation on the README's performance cases.

Each figure is the median of three runs of pipeline.run, each the first call
in a fresh process, so no cache or warm import flatters it. Inputs are built
before the clock starts. Run from the repository root:

    python scripts/benchmark.py            # every case
    python scripts/benchmark.py 49x49      # cases whose name contains "49x49"

Cases:
- bundled: fixtures/demo, baseline to proposed.
- random-P-R-F-O: a seeded pair at the input limits (100 nodes, 300 facts over
  all six predicates, about three-quarters false) with P principals, R roles,
  F functions and O objects. One iam:PassRole grant flipped from false to true
  opens a route. "all-entries" makes every principal an entry point.
- passrole-RxF: one entry principal able to pass R roles into F functions, so
  every role it reaches is evaluated against every other role through every
  function. The 49x49 pair is the one a reviewer built; 66x33 is the same shape.
"""

from __future__ import annotations

import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from attackgraph.snapshot import POLICY_CONTROLS  # noqa: E402

RUNS = 3


def _doc(snapshot_id: str, nodes: list, facts: list, entries: list, targets: list, expected: list) -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "synthetic": True,
        "model_version": "attackgraph-rules-v1",
        "coverage": {"policy_controls": {key: "resolved" for key in POLICY_CONTROLS}, "unmodelled_mechanisms": []},
        "nodes": nodes,
        "facts": facts,
        "entry_principals": entries,
        "protected_targets": targets,
        "expected_access": expected,
    }


def _node(node_id: str, kind: str, label: str | None = None) -> dict:
    return {"id": node_id, "kind": kind, "label": label or node_id, "account_id": "syn-a"}


def worst_case(snapshot_id: str, roles: int, functions: int, opened: bool) -> bytes:
    """One principal that can pass every role into every function it fully controls.

    In the baseline the grant for r0 is false; the proposal (opened) makes it true.
    Every role is protected, and no role has facts of its own, so each role the
    principal reaches has an unresolved candidate to every other role through
    every function. A protected object is added while the 100-node limit allows.
    """
    nodes = [_node("p0", "principal", "p")]
    nodes += [_node(f"r{i}", "role", "r") for i in range(roles)]
    nodes += [_node(f"l{i}", "lambda", "l") for i in range(functions)]
    with_object = len(nodes) < 100
    if with_object:
        nodes.append(_node("o0", "s3_object", "o"))
    facts = [
        {"id": f"t{i}", "predicate": "role_trusts_lambda_service", "subject": f"r{i}", "state": "true"} for i in range(roles)
    ]
    k = 0
    for i in range(roles):
        state = "true" if (opened or i) else "false"
        facts.append({"id": f"f{k}", "predicate": "iam_pass_role_to_lambda", "subject": "p0", "object": f"r{i}", "state": state})
        k += 1
    for j in range(functions):
        for predicate in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code"):
            facts.append({"id": f"f{k}", "predicate": predicate, "subject": "p0", "object": f"l{j}", "state": "true"})
            k += 1
    targets = [{"node": f"r{i}", "classification": "privileged_role"} for i in range(roles)]
    if with_object:
        targets.append({"node": "o0", "classification": "sensitive_object"})
    return json.dumps(_doc(snapshot_id, nodes, facts[:300], ["p0"], targets, [])).encode()


_KINDS = {
    "s3_get_object": (("p", "r"), "o"),
    "iam_pass_role_to_lambda": (("p", "r"), "r"),
    "lambda_create_function": (("p", "r"), "l"),
    "lambda_invoke_function": (("p", "r"), "l"),
    "controls_workload_code": (("p", "r"), "l"),
    "role_trusts_lambda_service": (("r",), None),
}


def random_pair(seed: int, principals: int, roles: int, functions: int, objects: int, entries: int) -> tuple[bytes, bytes]:
    """A pair at the input limits that differs in one iam:PassRole grant."""
    rng = random.Random(seed)
    ids = {
        "p": [f"p{i:02d}" for i in range(principals)],
        "r": [f"r{i:02d}" for i in range(roles)],
        "l": [f"l{i:02d}" for i in range(functions)],
        "o": [f"o{i:02d}" for i in range(objects)],
    }
    kinds = {"p": "principal", "r": "role", "l": "lambda", "o": "s3_object"}
    nodes = [_node(node_id, kinds[prefix]) for prefix, group in ids.items() for node_id in group]
    p0, r0, l0 = ids["p"][0], ids["r"][0], ids["l"][0]
    route = [
        ("lambda_create_function", p0, l0, "true"),
        ("lambda_invoke_function", p0, l0, "true"),
        ("controls_workload_code", p0, l0, "true"),
        ("role_trusts_lambda_service", r0, None, "true"),
        ("iam_pass_role_to_lambda", p0, r0, "false"),  # the grant the proposal flips
    ]
    seen = {(predicate, subject, obj) for predicate, subject, obj, _ in route}
    facts = [(f"f{i:03d}", *row) for i, row in enumerate(route)]
    while len(facts) < 300:
        predicate = rng.choice(sorted(_KINDS))
        subject_kinds, object_kind = _KINDS[predicate]
        subject = rng.choice(ids[rng.choice(subject_kinds)])
        obj = rng.choice(ids[object_kind]) if object_kind else None
        if (predicate, subject, obj) in seen:
            continue
        seen.add((predicate, subject, obj))
        facts.append((f"f{len(facts):03d}", predicate, subject, obj, "false" if rng.random() < 0.75 else "true"))

    targets = [{"node": r, "classification": "privileged_role"} for r in ids["r"][::3]]
    targets += [{"node": o, "classification": "sensitive_object"} for o in ids["o"][::3]]
    expected = [
        {"id": "ea-read", "principal": p0, "target": ids["o"][1], "relationship": "object_read"},
        {"id": "ea-role", "principal": p0, "target": ids["r"][1], "relationship": "role_use"},
    ]

    def build(snapshot_id: str, flipped: bool) -> bytes:
        records = []
        for fact_id, predicate, subject, obj, state in facts:
            if fact_id == "f004" and flipped:
                state = "true"
            record = {"id": fact_id, "predicate": predicate, "subject": subject, "state": state}
            if obj is not None:
                record["object"] = obj
            records.append(record)
        return json.dumps(_doc(snapshot_id, nodes, records, ids["p"][:entries], targets, expected)).encode()

    return build("baseline", False), build("proposal", True)


def _fixture_pair() -> tuple[bytes, bytes]:
    demo = ROOT / "fixtures" / "demo"
    return (demo / "baseline.json").read_bytes(), (demo / "proposed.json").read_bytes()


CASES = {
    "bundled": _fixture_pair,
    "random-20-30-20-30": lambda: random_pair(1, 20, 30, 20, 30, 2),
    "random-10-40-40-10": lambda: random_pair(2, 10, 40, 40, 10, 2),
    "random-10-40-40-10-all-entries": lambda: random_pair(3, 10, 40, 40, 10, 10),
    "passrole-49x49": lambda: (worst_case("baseline", 49, 49, False), worst_case("proposal", 49, 49, True)),
    "passrole-66x33": lambda: (worst_case("baseline", 66, 33, False), worst_case("proposal", 66, 33, True)),
}


def time_once(case: str) -> float:
    """One timed pipeline.run in this process; the inputs are built first."""
    from attackgraph.pipeline import run

    baseline, proposal = CASES[case]()
    started = time.perf_counter()
    result = run(baseline, "baseline.json", proposal, "proposal.json")
    elapsed = time.perf_counter() - started
    assert result.ok, "benchmark inputs must validate"
    return elapsed


def main(argv: list[str]) -> int:
    if argv[:1] == ["--once"]:
        print(f"{time_once(argv[1]):.6f}")
        return 0
    selected = [name for name in CASES if not argv or any(pattern in name for pattern in argv)]
    for name in selected:
        runs = []
        for _ in range(RUNS):
            out = subprocess.run(
                [sys.executable, __file__, "--once", name], check=True, capture_output=True, text=True, cwd=ROOT
            ).stdout
            runs.append(float(out))
        shown = ", ".join(f"{t:.3f}" for t in runs)
        print(f"{name:32s} median {statistics.median(runs):8.3f} s   runs {shown}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
