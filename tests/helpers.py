"""Fixture builders shared by the test modules."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from attackgraph.snapshot import Snapshot, load_snapshot

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

ENTRY = "p-ci-deployer"
ADMIN_ROLE = "r-deploy-admin"
RUNTIME_ROLE = "r-app-runtime"
PASSROLE_FACT = "f-ci-pass-deploy-admin"
ADMIN_FINDING = f"finding/{ENTRY}/{ADMIN_ROLE}/privileged_role_use"
ADMIN_CANDIDATE = f"B:{ENTRY}->{ADMIN_ROLE}@l-build-hook"

# Every Rule B prerequisite of the demo finding that is a declared fact.
RULE_B_FACTS = (
    PASSROLE_FACT,
    "f-ci-create-build-hook",
    "f-ci-invoke-build-hook",
    "f-ci-controls-build-hook-code",
    "f-deploy-admin-trusts-lambda",
)


def read_doc(relative: str) -> dict:
    return json.loads((FIXTURES / relative).read_text())


def baseline_doc() -> dict:
    return read_doc("demo/baseline.json")


def proposed_doc() -> dict:
    return read_doc("demo/proposed.json")


def to_bytes(doc: dict) -> bytes:
    return json.dumps(doc, indent=1).encode()


def to_snapshot(doc: dict, name: str = "test.json") -> Snapshot:
    result = load_snapshot(to_bytes(doc), name)
    assert result.ok, [str(issue) for issue in result.issues]
    return result.snapshot


def fact(doc: dict, fact_id: str) -> dict:
    return next(f for f in doc["facts"] if f["id"] == fact_id)


def set_state(doc: dict, fact_id: str, state: str) -> dict:
    fact(doc, fact_id)["state"] = state
    return doc


def remove_fact(doc: dict, fact_id: str) -> dict:
    doc["facts"] = [f for f in doc["facts"] if f["id"] != fact_id]
    return doc


def add_fact(doc: dict, fact_id: str, predicate: str, subject: str, obj: str | None, state: str) -> dict:
    record = {"id": fact_id, "predicate": predicate, "subject": subject, "state": state}
    if obj is not None:
        record["object"] = obj
    doc["facts"].append(record)
    return doc


def add_node(doc: dict, node_id: str, kind: str, label: str = "Test node", account: str = "syn-app-prod") -> dict:
    doc["nodes"].append({"id": node_id, "kind": kind, "label": label, "account_id": account})
    return doc


def add_workload(doc: dict, workload: str, subject: str = ENTRY, state: str = "true") -> dict:
    """A second Lambda workload the subject fully controls."""
    add_node(doc, workload, "lambda", "Second hook function")
    for predicate in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code"):
        add_fact(doc, f"f-{subject}-{predicate}-{workload}", predicate, subject, workload, state)
    return doc


def resolve_pointer(doc, pointer: str):
    value = doc
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def copy_doc(doc: dict) -> dict:
    return copy.deepcopy(doc)
