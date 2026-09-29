"""AC-11: the report and the graph match the displayed analysis."""

import re

from helpers import ADMIN_FINDING, baseline_doc, proposed_doc, read_doc, to_snapshot
from test_explain import FakeClient

from attackgraph.compare import compare_snapshots
from attackgraph.explain import BedrockExplainer, build_packet
from attackgraph.render import step_text, witness_dot
from attackgraph.report import build_report
from attackgraph.simulate import best_fix_for, fix_candidates


def demo():
    comparison = compare_snapshots(to_snapshot(baseline_doc(), "baseline.json"), to_snapshot(proposed_doc(), "proposed.json"))
    return comparison, fix_candidates(comparison)


def test_report_contains_findings_evidence_coverage_and_labels():
    comparison, fixes = demo()
    report = build_report(comparison, fixes, generated_at="2026-09-29T12:00:00Z")
    assert "**Synthetic configuration JSON.**" in report
    assert comparison.analysis_id in report and "attackgraph-rules-v1" in report
    assert "1 new high-risk finding in the proposal." in report
    assert "| Coverage | complete |" in report
    finding = comparison.proposal.findings[ADMIN_FINDING]
    assert f"`{ADMIN_FINDING}`" in report
    for fact_id in finding.fact_ids:
        assert f"`{fact_id}`" in report
    for ptr in finding.pointers:
        assert f"`{ptr}`" in report
    assert "`f-ci-pass-deploy-admin` **CHANGED**" in report
    assert "No AI explanation was requested" in report
    assert "No fix was simulated in this session." in report


def test_report_records_simulation_and_generated_explanation():
    comparison, fixes = demo()
    fix = best_fix_for(fixes, ADMIN_FINDING)
    packet = build_packet(comparison, comparison.delta(ADMIN_FINDING), fixes)
    result = BedrockExplainer("apac.amazon.nova-pro-v1:0", "ap-southeast-1", client=FakeClient()).explain(packet)
    report = build_report(comparison, fixes, simulation=fix, explanations=(result,))
    assert "simulated fix 0" in report
    assert "Verified in this model for: `" + ADMIN_FINDING + "`" in report
    assert "status **generated**" in report and "`apac.amazon.nova-pro-v1:0`" in report
    assert "request ID `req-123`" in report and "`ap-southeast-1`" in report
    assert "Generated explanation (Amazon Bedrock):" in report


def test_report_labels_unavailable_ai_and_shows_template():
    comparison, fixes = demo()
    packet = build_packet(comparison, comparison.delta(ADMIN_FINDING), fixes)
    result = BedrockExplainer("m", "r", client=FakeClient(stop="content_filtered")).explain(packet)
    report = build_report(comparison, fixes, explanations=(result,))
    assert "AI explanation unavailable" in report
    assert "Template summary (deterministic, not AI-generated):" in report


def test_report_escapes_untrusted_labels():
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(read_doc("examples/label-injection.json")))
    report = build_report(comparison, fix_candidates(comparison))
    assert "<script>" not in report and "](javascript" not in report


def test_incomplete_report_never_claims_safety():
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(read_doc("examples/unknown-prerequisite.json")))
    report = build_report(comparison, fix_candidates(comparison))
    assert "Analysis incomplete." in report and "No new modelled high-risk access" not in report
    assert "(provisional)" in report


def test_graph_edges_match_the_text_path():
    comparison, _ = demo()
    witness = comparison.proposal.findings[ADMIN_FINDING].witness
    dot = witness_dot(comparison.proposal, witness, comparison.changed_fact_ids)
    edges = re.findall(r'^"([^"]+)" -> "([^"]+)"', dot, flags=re.M)
    assert edges == [(c.subject, c.target) for c in witness]
    for candidate in witness:
        assert candidate.subject in step_text(candidate) and candidate.target in step_text(candidate)
    assert "CHANGED: f-ci-pass-deploy-admin" in dot


def test_graph_escapes_quotes_in_labels():
    doc = proposed_doc()
    doc["nodes"][0]["label"] = 'CI "deploy" user \\N'
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(doc))
    witness = comparison.proposal.findings[ADMIN_FINDING].witness
    dot = witness_dot(comparison.proposal, witness)
    assert 'CI \\"deploy\\" user \\\\N' in dot
