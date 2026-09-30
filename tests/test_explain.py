"""AC-8 (honest AI) and AC-10 (trust boundaries) with a fake Bedrock client."""

import json
import re
import time

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from helpers import ADMIN_FINDING, FIXTURES, baseline_doc, proposed_doc, read_doc, to_snapshot

from attackgraph import web
from attackgraph.compare import compare_snapshots
from attackgraph.explain import (
    SYSTEM_PROMPT,
    BedrockExplainer,
    build_packet,
    is_current,
    stored_segments,
    template_summary,
    user_prompt,
)
from attackgraph.render import md_escape, plain_segments
from attackgraph.simulate import fix_candidates
from attackgraph.story import build_story

VALID = {
    "finding_id": "A1",
    "summary": "The proposal sets F1 to true, so P1 can run code as the privileged role R1 through L1. X1 removes this finding.",
    "evidence_ids": ["F1", "D1"],
    "fix_candidate_id": "X1",
    "limitations": "Synthetic model only; nothing was deployed.",
}


class FakeClient:
    def __init__(self, reply=None, stop="end_turn", exc=None, delay=0.0):
        self.reply = json.dumps(VALID) if reply is None else reply
        self.stop, self.exc, self.delay = stop, exc, delay
        self.calls = []

    def converse(self, **request):
        self.calls.append(request)
        if self.delay:
            time.sleep(self.delay)
        if self.exc:
            raise self.exc
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": self.reply}]}},
            "stopReason": self.stop,
            "usage": {"inputTokens": 1200, "outputTokens": 180},
            "metrics": {"latencyMs": 900},
            "ResponseMetadata": {"RequestId": "req-123"},
        }


@pytest.fixture
def demo():
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(proposed_doc()))
    fixes = fix_candidates(comparison)
    return comparison, fixes, build_packet(comparison, comparison.delta(ADMIN_FINDING), fixes)


def engine_state(comparison):
    return (
        comparison.verdict,
        tuple((d.id, d.status, d.severity, d.provisional) for d in comparison.deltas),
        comparison.baseline.high_risk_count,
        comparison.proposal.high_risk_count,
        comparison.proposal.coverage.complete,
    )


def explainer(client, **kwargs):
    return BedrockExplainer("test-model", "ap-southeast-1", client=client, **kwargs)


def test_valid_reply_is_translated_back_to_real_ids_and_shown_by_name(demo):
    comparison, _, packet = demo
    result = explainer(FakeClient()).explain(packet)
    assert result.ok and result.request_id == "req-123" and result.input_tokens == 1200
    assert ("node", "r-deploy-admin") in result.summary and ("id", "f-ci-pass-deploy-admin") in result.summary
    assert result.evidence_ids == ("f-ci-pass-deploy-admin", "same-account check")
    assert result.cited_fix == "revoke/f-ci-pass-deploy-admin"
    assert is_current(result, comparison.analysis_id)
    rendered = web.reply(result.summary, build_story(comparison, comparison.delta(ADMIN_FINDING)).nodes)
    assert 'title="p-ci-deployer">' in rendered and "CI deploy user (build pipeline)</span>" in rendered
    assert 'class="ag-ent protected" title="r-deploy-admin"' in rendered  # the protected role is marked as such
    assert '<span class="ag-mono">f-ci-pass-deploy-admin</span>' in rendered  # facts keep their IDs
    assert "P1" not in rendered and "R1" not in rendered


def test_reply_names_are_escaped_and_set_apart_from_the_prose():
    injected = read_doc("examples/label-injection.json")
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(injected))
    delta = comparison.delta(ADMIN_FINDING)
    result = explainer(FakeClient()).explain(build_packet(comparison, delta, fix_candidates(comparison)))
    rendered = web.reply(result.summary, build_story(comparison, delta).nodes)
    assert "<script>" not in rendered and "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    # The injected sentence appears only inside its entity chip, never as loose prose.
    label = next(n["label"] for n in injected["nodes"] if n["id"] == "r-deploy-admin")
    chip = f'<span class="ag-ent protected" title="r-deploy-admin">{web.icon("admin_panel_settings")}{web.esc(label)}</span>'
    assert chip in rendered and rendered.count(web.esc(label)) == rendered.count(chip)


def test_stored_reply_restores_the_segments_the_live_app_shows(demo):
    _, _, packet = demo
    result = explainer(FakeClient()).explain(packet)
    assert stored_segments(plain_segments(result.summary), packet) == result.summary
    recorded = json.loads((FIXTURES.parent / "docs" / "evidence" / "recorded-explanation.json").read_text())
    segments = stored_segments(recorded["summary"], packet)
    assert ("id", "revoke/f-ci-pass-deploy-admin") in segments  # the fix ID is not split at the fact ID inside it
    assert ("node", "p-ci-deployer") in segments and ("node", "l-build-hook") in segments
    assert plain_segments(segments) == recorded["summary"]


@pytest.mark.parametrize(
    "client, status",
    [
        (FakeClient(reply="Sure! Here is my explanation."), "invalid"),
        (FakeClient(reply=json.dumps({**VALID, "evidence_ids": ["F99"]})), "invalid"),
        (FakeClient(reply=json.dumps({**VALID, "summary": VALID["summary"] + " R9 is also exposed."})), "invalid"),
        (FakeClient(reply=json.dumps({**VALID, "fix_candidate_id": "X7"})), "invalid"),
        (FakeClient(reply=json.dumps({**VALID, "finding_id": "A2"})), "invalid"),
        (FakeClient(reply=json.dumps({**VALID, "severity": "Low"})), "invalid"),
        (FakeClient(reply=json.dumps({**VALID, "summary": "x" * 2000})), "invalid"),
        (FakeClient(stop="max_tokens"), "invalid"),
        (FakeClient(stop="content_filtered"), "refused"),
        (FakeClient(stop="guardrail_intervened"), "refused"),
        (FakeClient(exc=ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Converse")), "unavailable"),
        (FakeClient(exc=NoCredentialsError()), "unavailable"),
        (FakeClient(exc=RuntimeError("boom")), "unavailable"),
    ],
)
def test_bad_replies_never_change_engine_results(demo, client, status):
    comparison, fixes, packet = demo
    before = engine_state(comparison)
    result = explainer(client).explain(packet)
    assert result.status == status and not result.ok
    assert result.summary == () and result.error
    assert engine_state(comparison) == before
    assert "Verified in this model" in template_summary(comparison, comparison.delta(ADMIN_FINDING), fixes)


def test_timeout_falls_back(demo):
    comparison, _, packet = demo
    before = engine_state(comparison)
    started = time.monotonic()
    result = explainer(FakeClient(delay=2.0), timeout=0.2).explain(packet)
    assert result.status == "timeout"
    assert time.monotonic() - started < 1.5
    assert engine_state(comparison) == before


def test_successful_replies_are_cached_and_labelled(demo):
    _, _, packet = demo
    client = FakeClient()
    ai = explainer(client)
    first, second = ai.explain(packet), ai.explain(packet)
    assert len(client.calls) == 1
    assert not first.cached and second.cached and second.request_id == first.request_id


def test_ai_can_be_disabled(demo, monkeypatch):
    _, _, packet = demo
    monkeypatch.setenv("ATTACKGRAPH_AI", "off")
    client = FakeClient()
    assert explainer(client).explain(packet).status == "disabled"
    assert client.calls == []


def test_request_has_no_tools_and_bounded_output(demo):
    _, _, packet = demo
    client = FakeClient()
    explainer(client).explain(packet)
    request = client.calls[0]
    assert "toolConfig" not in request
    assert request["inferenceConfig"]["maxTokens"] <= 1000


def test_stale_reply_is_not_current_for_new_inputs(demo):
    comparison, _, packet = demo
    result = explainer(FakeClient()).explain(packet)
    changed = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(read_doc("examples/unknown-prerequisite.json")))
    assert changed.analysis_id != comparison.analysis_id
    assert not is_current(result, changed.analysis_id)


def test_ac10_prompt_carries_no_uploaded_text():
    injected = read_doc("examples/label-injection.json")
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(injected))
    fixes = fix_candidates(comparison)
    packet = build_packet(comparison, comparison.delta(ADMIN_FINDING), fixes)
    prompt = SYSTEM_PROMPT + user_prompt(packet)
    labels = [n["label"] for n in injected["nodes"]]
    ids = [n["id"] for n in injected["nodes"]] + [f["id"] for f in injected["facts"]]
    for text in labels + ids + ["IGNORE ALL PREVIOUS", "<script>", "credentials."]:
        assert text not in prompt, text
    plain = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(proposed_doc()))
    assert engine_state(comparison)[1:] == engine_state(plain)[1:]


def test_ac10_labels_are_escaped_for_markdown():
    label = read_doc("examples/label-injection.json")["nodes"][3]["label"]
    escaped = md_escape(label)
    # Every Markdown, HTML, directive and math delimiter must arrive backslash-escaped.
    assert re.search(r"(?<!\\)[<>\[\]()$:`*_!]", escaped) is None, escaped


def test_label_injection_fixture_matches_demo_structure():
    injected = read_doc("examples/label-injection.json")
    assert {n["id"] for n in injected["nodes"]} == {n["id"] for n in proposed_doc()["nodes"]}
    assert (FIXTURES / "examples" / "label-injection.json").stat().st_size < 1024 * 1024


def test_aws_error_messages_are_redacted(demo):
    _, _, packet = demo
    message = "User: arn:aws:iam::123456789012:root is not authorized to perform bedrock:InvokeModel on account 123456789012"
    error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": message}}, "Converse")
    result = explainer(FakeClient(exc=error)).explain(packet)
    assert "123456789012" not in result.error and "arn:aws" not in result.error
    assert "AccessDeniedException" in result.error and "<arn>" in result.error


def test_expected_access_checks_are_citable_evidence(demo):
    # A live Nova Pro reply (AC-9 run 9, explain-v1) cited E1 and E2; both are packet identifiers.
    _, _, packet = demo
    reply = json.dumps({**VALID, "evidence_ids": ["F1", "E1", "E2"]})
    result = explainer(FakeClient(reply=reply)).explain(packet)
    assert result.ok
    assert result.evidence_ids == ("f-ci-pass-deploy-admin", "ea-ci-reads-build-artifacts", "ea-ci-deploys-app-runtime")


def test_prompt_pins_assumption_wording_and_entity_kinds():
    assert "never call it trusted or compromised" in SYSTEM_PROMPT
    assert '"Lambda workload L1"' in SYSTEM_PROMPT
