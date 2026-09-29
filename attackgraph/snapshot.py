"""Snapshot records, parsing and validation.

Validation runs in three passes and stops at the first pass that reports a
problem: bytes to JSON (size, encoding, duplicate keys, control characters,
raw policy content), the bundled JSON Schema (shape, unknown fields, enums),
then references and predicate signatures. Callers must not analyse either
file of a comparison while any issue remains.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from functools import cached_property
from importlib import resources
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from . import MODEL_VERSION, SCHEMA_VERSION

MAX_BYTES = 1024 * 1024
MAX_ISSUES = 50

ID_PATTERN = "^[a-z0-9][a-z0-9._-]{0,63}$"
ACCOUNT_PATTERN = "^syn-[a-z0-9-]{1,32}$"

POLICY_CONTROLS = {
    "permissions_boundaries": "Permissions boundaries",
    "service_control_policies": "Service control policies",
    "resource_policies": "Resource policies",
    "conditions": "Policy conditions",
    "explicit_denies": "Explicit denies",
}
UNMODELLED_MECHANISMS = {
    "general_assume_role": "General sts:AssumeRole chains",
    "ec2_instance_profiles": "EC2 instance profiles",
    "cross_account_access": "Cross-account access",
    "other_service_role_passing": "Role passing to services other than Lambda",
    "other": "Other access mechanisms",
}
KIND_TITLES = {
    "principal": "Principal",
    "role": "Role",
    "lambda": "Lambda workload",
    "s3_object": "S3 object",
}
TARGET_KINDS = {"privileged_role": "role", "sensitive_object": "s3_object"}
RELATIONSHIP_KINDS = {"object_read": "s3_object", "role_use": "role"}

# Capitalised IAM policy grammar. Snapshot keys are lower-case, so any of these
# means a policy document was pasted in place of declared facts.
RAW_POLICY_KEYS = frozenset(
    {
        "Version",
        "Statement",
        "Sid",
        "Effect",
        "Action",
        "NotAction",
        "Resource",
        "NotResource",
        "Principal",
        "NotPrincipal",
        "Condition",
        "PolicyDocument",
        "AssumeRolePolicyDocument",
        "PolicyName",
    }
)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class PredicateSpec:
    name: str
    subject_kinds: tuple[str, ...]
    object_kinds: tuple[str, ...] | None  # None marks a unary predicate
    category: str  # permission | trust | assumption
    template: str

    def describe(self, subject: str, obj: str | None) -> str:
        return self.template.format(subject=subject, object=obj)


PREDICATES = {
    spec.name: spec
    for spec in (
        PredicateSpec(
            "s3_get_object",
            ("principal", "role"),
            ("s3_object",),
            "permission",
            "{subject} has effective s3:GetObject on {object}",
        ),
        PredicateSpec(
            "iam_pass_role_to_lambda",
            ("principal", "role"),
            ("role",),
            "permission",
            "{subject} can pass role {object} to Lambda (iam:PassRole)",
        ),
        PredicateSpec(
            "lambda_create_function",
            ("principal", "role"),
            ("lambda",),
            "permission",
            "{subject} can create Lambda workload {object}",
        ),
        PredicateSpec(
            "lambda_invoke_function",
            ("principal", "role"),
            ("lambda",),
            "permission",
            "{subject} can invoke Lambda workload {object}",
        ),
        PredicateSpec(
            "controls_workload_code",
            ("principal", "role"),
            ("lambda",),
            "assumption",
            "{subject} controls the code of {object}",
        ),
        PredicateSpec(
            "role_trusts_lambda_service",
            ("role",),
            None,
            "trust",
            "{subject} trust policy allows the Lambda service",
        ),
    )
}


def pointer(*parts: Any) -> str:
    """Build an RFC 6901 JSON pointer."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _pointer_sort_key(value: str) -> tuple:
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in value.split("/"))


@dataclass(frozen=True)
class Issue:
    pointer: str
    message: str

    def __str__(self) -> str:
        return f"{self.pointer or '(file)'}: {self.message}"


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    label: str
    account_id: str
    pointer: str


@dataclass(frozen=True)
class Fact:
    id: str
    predicate: str
    subject: str
    object: str | None
    state: str
    pointer: str

    @property
    def triple(self) -> tuple[str, str, str | None]:
        return (self.predicate, self.subject, self.object)

    @property
    def spec(self) -> PredicateSpec:
        return PREDICATES[self.predicate]

    def describe(self) -> str:
        return self.spec.describe(self.subject, self.object)


@dataclass(frozen=True)
class ProtectedTarget:
    node: str
    classification: str
    pointer: str


@dataclass(frozen=True)
class ExpectedAccess:
    id: str
    principal: str
    target: str
    relationship: str
    pointer: str


@dataclass(frozen=True)
class Revision:
    """A change applied in memory to a loaded snapshot (simulation only)."""

    fact_id: str
    from_state: str
    to_state: str


@dataclass(frozen=True, eq=False)
class Snapshot:
    snapshot_id: str
    name: str
    source_name: str
    sha256: str
    size_bytes: int
    policy_controls: dict[str, str]
    unmodelled_mechanisms: tuple[str, ...]
    nodes: dict[str, Node]
    facts: dict[str, Fact]
    entry_principals: tuple[str, ...]
    protected_targets: dict[str, ProtectedTarget]
    expected_access: tuple[ExpectedAccess, ...]
    revisions: tuple[Revision, ...] = ()
    schema_version: str = SCHEMA_VERSION
    model_version: str = MODEL_VERSION
    synthetic: bool = True

    @cached_property
    def fact_index(self) -> dict[tuple[str, str, str | None], Fact]:
        return {fact.triple: fact for fact in self.facts.values()}

    def fact_for(self, predicate: str, subject: str, obj: str | None = None) -> Fact | None:
        return self.fact_index.get((predicate, subject, obj))

    def nodes_of_kind(self, kind: str) -> list[str]:
        return sorted(node.id for node in self.nodes.values() if node.kind == kind)

    @property
    def is_simulated(self) -> bool:
        return bool(self.revisions)

    def with_fact_state(self, fact_id: str, state: str) -> Snapshot:
        """Return a copy with one fact's state changed; the record is kept."""
        fact = self.facts[fact_id]
        facts = dict(self.facts)
        facts[fact_id] = replace(fact, state=state)
        return replace(
            self,
            facts=facts,
            revisions=self.revisions + (Revision(fact_id, fact.state, state),),
        )


@dataclass(frozen=True)
class LoadResult:
    snapshot: Snapshot | None
    issues: tuple[Issue, ...]
    source_name: str
    sha256: str
    size_bytes: int

    @property
    def ok(self) -> bool:
        return self.snapshot is not None


class _JsonObject(dict):
    """dict that remembers keys repeated in the source object."""

    duplicates: tuple[str, ...] = ()

    @classmethod
    def from_pairs(cls, pairs: list[tuple[str, Any]]) -> _JsonObject:
        obj = cls()
        repeated = []
        for key, value in pairs:
            if key in obj:
                repeated.append(key)
            obj[key] = value
        obj.duplicates = tuple(repeated)
        return obj


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name} is not allowed")


def load_snapshot(data: bytes, source_name: str = "snapshot.json") -> LoadResult:
    digest = hashlib.sha256(data).hexdigest()

    def fail(issues: list[Issue]) -> LoadResult:
        ordered = sorted(set(issues), key=lambda i: (_pointer_sort_key(i.pointer), i.message))
        return LoadResult(None, tuple(ordered[:MAX_ISSUES]), source_name, digest, len(data))

    if len(data) > MAX_BYTES:
        return fail([Issue("", f"file is {len(data):,} bytes; the limit is {MAX_BYTES:,} bytes (1 MiB)")])
    if not data.strip():
        return fail([Issue("", "file is empty")])
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return fail([Issue("", f"file is not UTF-8 text (invalid byte at offset {exc.start})")])
    try:
        doc = json.loads(text, object_pairs_hook=_JsonObject.from_pairs, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        return fail([Issue("", f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")])
    except RecursionError:
        return fail([Issue("", "invalid JSON: nesting is too deep")])
    except ValueError as exc:
        return fail([Issue("", f"invalid JSON: {exc}")])

    if not isinstance(doc, dict):
        return fail([Issue("", "the top-level value must be a JSON object")])
    for check in (_structural_issues, _schema_issues, _semantic_issues):
        issues = list(check(doc))
        if issues:
            return fail(issues)
    return LoadResult(_build(doc, data, source_name, digest), (), source_name, digest, len(data))


def _structural_issues(doc: Any) -> Iterator[Issue]:
    stack: list[tuple[tuple, Any]] = [((), doc)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            for key in getattr(value, "duplicates", ()):
                yield Issue(pointer(*path, key), "duplicate key in the same object")
            for key, child in value.items():
                if key in RAW_POLICY_KEYS:
                    yield Issue(
                        pointer(*path, key),
                        "raw IAM policy content is not supported; declare resolved facts instead",
                    )
                if _CONTROL_CHARS.search(key):
                    yield Issue(pointer(*path), "control characters are not allowed in keys")
                stack.append(((*path, key), child))
        elif isinstance(value, list):
            stack.extend(((*path, i), child) for i, child in enumerate(value))
        elif isinstance(value, str) and _CONTROL_CHARS.search(value):
            yield Issue(pointer(*path), "control characters (including line breaks) are not allowed")


_VALIDATOR: Draft202012Validator | None = None


def schema_document() -> dict:
    return json.loads(resources.files(__package__).joinpath("snapshot.schema.json").read_text("utf-8"))


def _validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        schema = schema_document()
        Draft202012Validator.check_schema(schema)
        _VALIDATOR = Draft202012Validator(schema)
    return _VALIDATOR


def _schema_issues(doc: dict) -> Iterator[Issue]:
    for error in _validator().iter_errors(doc):
        yield from _format_schema_error(error)


def _format_schema_error(error) -> Iterator[Issue]:
    path = list(error.absolute_path)
    where = pointer(*path)
    kind = error.validator
    if kind == "required":
        for key in error.validator_value:
            if isinstance(error.instance, dict) and key not in error.instance:
                yield Issue(pointer(*path, key), "required field is missing")
        return
    if kind == "additionalProperties":
        allowed = set(error.schema.get("properties", {}))
        for key in sorted(set(error.instance) - allowed):
            yield Issue(pointer(*path, key), "unknown field is not allowed")
        return
    if kind == "const":
        if where == "/synthetic":
            message = "must be true: only synthetic fixtures are accepted"
        elif where == "/schema_version":
            message = f"unsupported schema version; expected {json.dumps(error.validator_value)}"
        elif where == "/model_version":
            message = f"unsupported model version; expected {json.dumps(error.validator_value)}"
        else:
            message = f"must be {json.dumps(error.validator_value)}"
        yield Issue(where, message)
        return
    if kind == "enum":
        options = ", ".join(json.dumps(v) for v in error.validator_value)
        yield Issue(where, f"must be one of {options}")
        return
    if kind == "pattern":
        if error.validator_value == ACCOUNT_PATTERN:
            message = 'must be a synthetic account ID starting with "syn-" (for example "syn-app-prod")'
        elif error.validator_value == ID_PATTERN:
            message = "must use lower-case letters, digits, '.', '_' or '-', start with a letter or digit, and be at most 64 characters"
        else:
            message = "has an invalid format"
        yield Issue(where, message)
        return
    if kind == "type":
        yield Issue(where, f"must be of type {error.validator_value}")
        return
    if kind == "maxItems":
        yield Issue(where, f"has too many items (maximum {error.validator_value})")
        return
    if kind == "minItems":
        yield Issue(where, f"must contain at least {error.validator_value} item(s)")
        return
    if kind == "maxLength":
        yield Issue(where, f"is too long (maximum {error.validator_value} characters)")
        return
    if kind == "minLength":
        yield Issue(where, "must not be empty")
        return
    if kind == "uniqueItems":
        yield Issue(where, "items must be unique")
        return
    yield Issue(where, error.message)


def _semantic_issues(doc: dict) -> Iterator[Issue]:
    nodes: dict[str, tuple[int, dict]] = {}
    for i, node in enumerate(doc["nodes"]):
        if node["id"] in nodes:
            first = nodes[node["id"]][0]
            yield Issue(pointer("nodes", i, "id"), f'duplicate node ID "{node["id"]}" (first defined at /nodes/{first})')
        else:
            nodes[node["id"]] = (i, node)

    def ref(where: str, node_id: str, kinds: tuple[str, ...], role: str) -> Iterator[Issue]:
        if node_id not in nodes:
            yield Issue(where, f'references unknown node "{node_id}"')
            return
        kind = nodes[node_id][1]["kind"]
        if kind not in kinds:
            expected = " or ".join(kinds)
            yield Issue(where, f'{role} must be a node of kind {expected}, but "{node_id}" has kind {kind}')

    fact_ids: dict[str, int] = {}
    triples: dict[tuple, tuple[int, dict]] = {}
    for i, fact in enumerate(doc["facts"]):
        spec = PREDICATES[fact["predicate"]]
        if fact["id"] in fact_ids:
            yield Issue(pointer("facts", i, "id"), f'duplicate fact ID "{fact["id"]}" (first defined at /facts/{fact_ids[fact["id"]]})')
        else:
            fact_ids[fact["id"]] = i
        yield from ref(pointer("facts", i, "subject"), fact["subject"], spec.subject_kinds, f"the subject of {spec.name}")
        if spec.object_kinds is None:
            if "object" in fact:
                yield Issue(pointer("facts", i, "object"), f"{spec.name} does not take an object")
        elif "object" not in fact:
            yield Issue(pointer("facts", i, "object"), f"required field is missing for {spec.name}")
        else:
            yield from ref(pointer("facts", i, "object"), fact["object"], spec.object_kinds, f"the object of {spec.name}")
        triple = (fact["predicate"], fact["subject"], fact.get("object"))
        if triple in triples:
            j, other = triples[triple]
            conflict = " with a conflicting state" if other["state"] != fact["state"] else ""
            yield Issue(
                pointer("facts", i),
                f'duplicate fact{conflict}: "{other["id"]}" at /facts/{j} already declares {spec.describe(triple[1], triple[2])}',
            )
        else:
            triples[triple] = (i, fact)

    entries: set[str] = set()
    for i, entry in enumerate(doc["entry_principals"]):
        if entry in entries:
            yield Issue(pointer("entry_principals", i), f'duplicate entry principal "{entry}"')
        entries.add(entry)
        yield from ref(pointer("entry_principals", i), entry, ("principal",), "an entry principal")

    targets: set[str] = set()
    for i, target in enumerate(doc["protected_targets"]):
        where = pointer("protected_targets", i, "node")
        if target["node"] in targets:
            yield Issue(where, f'"{target["node"]}" is already a protected target')
        targets.add(target["node"])
        kind = TARGET_KINDS[target["classification"]]
        yield from ref(where, target["node"], (kind,), f"a {target['classification']} target")

    check_ids: set[str] = set()
    for i, check in enumerate(doc["expected_access"]):
        if check["id"] in check_ids:
            yield Issue(pointer("expected_access", i, "id"), f'duplicate expected-access ID "{check["id"]}"')
        check_ids.add(check["id"])
        if check["principal"] not in entries:
            yield Issue(
                pointer("expected_access", i, "principal"),
                f'"{check["principal"]}" must be listed in entry_principals',
            )
        kind = RELATIONSHIP_KINDS[check["relationship"]]
        yield from ref(pointer("expected_access", i, "target"), check["target"], (kind,), f"the target of {check['relationship']}")
        if check["target"] in targets:
            yield Issue(
                pointer("expected_access", i, "target"),
                f'"{check["target"]}" is a protected target; access to it is always a high-risk finding, not expected access',
            )


def _build(doc: dict, data: bytes, source_name: str, digest: str) -> Snapshot:
    return Snapshot(
        snapshot_id=doc["snapshot_id"],
        name=doc.get("name") or doc["snapshot_id"],
        source_name=source_name,
        sha256=digest,
        size_bytes=len(data),
        policy_controls={key: doc["coverage"]["policy_controls"][key] for key in POLICY_CONTROLS},
        unmodelled_mechanisms=tuple(doc["coverage"]["unmodelled_mechanisms"]),
        nodes={
            n["id"]: Node(n["id"], n["kind"], n["label"], n["account_id"], pointer("nodes", i))
            for i, n in enumerate(doc["nodes"])
        },
        facts={
            f["id"]: Fact(f["id"], f["predicate"], f["subject"], f.get("object"), f["state"], pointer("facts", i))
            for i, f in enumerate(doc["facts"])
        },
        entry_principals=tuple(doc["entry_principals"]),
        protected_targets={
            t["node"]: ProtectedTarget(t["node"], t["classification"], pointer("protected_targets", i))
            for i, t in enumerate(doc["protected_targets"])
        },
        expected_access=tuple(
            ExpectedAccess(c["id"], c["principal"], c["target"], c["relationship"], pointer("expected_access", i))
            for i, c in enumerate(doc["expected_access"])
        ),
    )
