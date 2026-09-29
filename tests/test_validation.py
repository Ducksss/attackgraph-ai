"""AC-3 (malformed input) and AC-10 (oversized or unsupported uploads)."""

import json

import pytest
from helpers import FIXTURES, baseline_doc, proposed_doc, to_bytes
from jsonschema import Draft202012Validator

from attackgraph.pipeline import run
from attackgraph.snapshot import MAX_BYTES, load_snapshot, schema_document


def issues_for(doc_or_bytes) -> list[tuple[str, str]]:
    data = doc_or_bytes if isinstance(doc_or_bytes, bytes) else to_bytes(doc_or_bytes)
    result = load_snapshot(data, "upload.json")
    assert not result.ok
    return [(i.pointer, i.message) for i in result.issues]


def assert_issue(issues, pointer, fragment):
    assert any(p == pointer and fragment in m for p, m in issues), issues


def test_schema_file_is_valid_and_bundled_fixtures_conform():
    schema = schema_document()
    Draft202012Validator.check_schema(schema)
    for path in (FIXTURES / "demo").glob("*.json"):
        assert load_snapshot(path.read_bytes(), path.name).ok, path


def test_invalid_json_reports_line_and_column():
    issues = issues_for(b'{"schema_version": "1.0",\n  "snapshot_id": }')
    assert issues[0][0] == "" and "line 2" in issues[0][1]


@pytest.mark.parametrize(
    "mutate, pointer, fragment",
    [
        (lambda d: d["nodes"].append(dict(d["nodes"][0])), "/nodes/6/id", "duplicate node ID"),
        (lambda d: d["facts"][0].update(object="r-missing"), "/facts/0/object", 'unknown node "r-missing"'),
        (lambda d: d["facts"][0].update(note="free text"), "/facts/0/note", "unknown field"),
        (lambda d: d["facts"][0].update(state=True), "/facts/0/state", "must be one of"),
        (lambda d: d["facts"][0].update(state="maybe"), "/facts/0/state", "must be one of"),
        (lambda d: d.update(schema_version="2.0"), "/schema_version", "unsupported schema version"),
        (lambda d: d.update(model_version="other-model"), "/model_version", "unsupported model version"),
        (lambda d: d.update(synthetic=False), "/synthetic", "only synthetic fixtures"),
        (lambda d: d.pop("coverage"), "/coverage", "required field is missing"),
        (lambda d: d["coverage"]["policy_controls"].pop("conditions"), "/coverage/policy_controls/conditions", "required"),
        (lambda d: d["nodes"][0].update(account_id="123456789012"), "/nodes/0/account_id", "synthetic account ID"),
        (lambda d: d["nodes"][0].update(id="Bad ID"), "/nodes/0/id", "lower-case letters"),
        (lambda d: d["nodes"][0].update(label="line one\nline two"), "/nodes/0/label", "control characters"),
        (lambda d: d["facts"][7].update(object="r-deploy-admin"), "/facts/7/object", "must be a node of kind s3_object"),
        (lambda d: d["facts"][5].update(object="l-build-hook"), "/facts/5/object", "does not take an object"),
        (lambda d: d["entry_principals"].append("r-app-runtime"), "/entry_principals/1", "must be a node of kind principal"),
        (lambda d: d["protected_targets"][0].update(node="o-build-artifacts"), "/protected_targets/0/node", "must be a node of kind role"),
        (lambda d: d["expected_access"][0].update(principal="r-app-runtime"), "/expected_access/0/principal", "entry_principals"),
        (lambda d: d["expected_access"][0].update(target="o-customer-export"), "/expected_access/0/target", "protected target"),
        (lambda d: d["nodes"][0].update(Statement=[{"Effect": "Allow"}]), "/nodes/0/Statement", "raw IAM policy"),
    ],
)
def test_field_level_errors(mutate, pointer, fragment):
    doc = proposed_doc()
    mutate(doc)
    assert_issue(issues_for(doc), pointer, fragment)


def test_conflicting_duplicate_fact_is_rejected():
    doc = proposed_doc()
    clone = dict(doc["facts"][1], id="f-duplicate", state="false")
    doc["facts"].append(clone)
    assert_issue(issues_for(doc), f"/facts/{len(doc['facts']) - 1}", "conflicting state")


def test_duplicate_json_keys_are_rejected():
    text = to_bytes(proposed_doc()).decode().replace('"state": "true"', '"state": "true", "state": "false"', 1)
    issues = issues_for(text.encode())
    assert any("duplicate key" in m for _, m in issues), issues


def test_nan_and_non_utf8_are_rejected():
    assert "non-standard JSON" in issues_for(b'{"a": NaN}')[0][1]
    assert "not UTF-8" in issues_for(b'\xff\xfe{}')[0][1]


def test_top_level_must_be_object():
    assert "JSON object" in issues_for(b"[]")[0][1]


def test_oversized_upload_is_rejected_before_parsing():
    data = b" " * (MAX_BYTES + 1)
    assert "limit is 1,048,576 bytes" in issues_for(data)[0][1]


def test_unsupported_formats_are_rejected():
    terraform = b'resource "aws_iam_role" "admin" {\n  name = "admin"\n}\n'
    assert "invalid JSON" in issues_for(terraform)[0][1]
    raw_policy = json.dumps({"Version": "2012-10-17", "Statement": []}).encode()
    assert any("raw IAM policy" in m for _, m in issues_for(raw_policy))


def test_invalid_file_blocks_analysis_of_both_files():
    good = to_bytes(baseline_doc())
    bad = (FIXTURES / "examples" / "invalid-references.json").read_bytes()
    result = run(good, "baseline.json", bad, "proposed.json")
    assert result.comparison is None and result.fixes == ()
    assert result.baseline.ok and not result.proposal.ok
    messages = [str(i) for i in result.proposal.issues]
    assert any("/facts/1/object" in m and "r-missing-role" in m for m in messages)
    assert any("duplicate node ID" in m for m in messages)
    assert any("must be a node of kind s3_object" in m for m in messages)


def test_example_schema_errors_are_reported_per_field():
    data = (FIXTURES / "examples" / "invalid-schema.json").read_bytes()
    pointers = {p for p, _ in issues_for(data)}
    assert {"/facts/0/state", "/nodes/0/comment", "/nodes/1/account_id"} <= pointers
