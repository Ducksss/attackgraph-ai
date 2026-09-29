"""AC-1, AC-2, AC-4 and AC-6: rule semantics, evidence integrity, routes and cycles."""

import pytest
from helpers import (
    ADMIN_CANDIDATE,
    ADMIN_FINDING,
    ADMIN_ROLE,
    ENTRY,
    PASSROLE_FACT,
    RULE_B_FACTS,
    RUNTIME_ROLE,
    add_fact,
    add_workload,
    baseline_doc,
    copy_doc,
    proposed_doc,
    read_doc,
    remove_fact,
    resolve_pointer,
    set_state,
    to_snapshot,
)

from attackgraph.analysis import analyze
from attackgraph.compare import compare_snapshots
from attackgraph.simulate import best_fix_for, fix_candidates


def test_ac1_baseline_proposal_and_repair():
    baseline, proposal = to_snapshot(baseline_doc()), to_snapshot(proposed_doc())
    assert baseline.facts[PASSROLE_FACT].state == "false"
    comparison = compare_snapshots(baseline, proposal)

    assert comparison.baseline.high_risk_count == 0
    assert comparison.proposal.high_risk_count == 1
    assert [(d.id, d.status, d.confirmed) for d in comparison.deltas] == [(ADMIN_FINDING, "added", True)]
    for analysis in (comparison.baseline, comparison.proposal):
        others = [p for p in analysis.candidates[ADMIN_CANDIDATE].prerequisites if p.fact_id != PASSROLE_FACT]
        assert others and all(p.state == "true" for p in others)

    fix = best_fix_for(fix_candidates(comparison), ADMIN_FINDING)
    assert fix is not None and fix.fact_id == PASSROLE_FACT
    assert fix.simulated.snapshot.facts[PASSROLE_FACT].state == "false"
    assert fix.simulated.high_risk_count == 0 and fix.verified_for(ADMIN_FINDING)

    repaired = to_snapshot(read_doc("demo/repaired.json"))
    back = compare_snapshots(proposal, repaired)
    assert back.proposal.high_risk_count == 0
    assert [(d.status, d.confirmed) for d in back.deltas] == [("removed", True)]


@pytest.mark.parametrize("fact_id", RULE_B_FACTS)
def test_ac2_each_declared_prerequisite_false_blocks_the_relationship(fact_id):
    analysis = analyze(to_snapshot(set_state(proposed_doc(), fact_id, "false")))
    assert analysis.candidates[ADMIN_CANDIDATE].state == "false"
    assert ADMIN_FINDING not in analysis.findings and ADMIN_FINDING not in analysis.potential


def test_ac2_cross_account_prerequisite_never_establishes_the_relationship():
    doc = proposed_doc()
    next(n for n in doc["nodes"] if n["id"] == ADMIN_ROLE)["account_id"] = "syn-other-account"
    analysis = analyze(to_snapshot(doc))
    candidate = analysis.candidates[ADMIN_CANDIDATE]
    same_account = next(p for p in candidate.prerequisites if p.key == "same_account")
    assert same_account.state == "unknown" and candidate.state == "unknown"
    assert ADMIN_FINDING not in analysis.findings
    assert not analysis.coverage.complete


def test_ac2_unresolved_policy_restrictions_never_establish_the_relationship():
    doc = proposed_doc()
    doc["coverage"]["policy_controls"]["explicit_denies"] = "unresolved"
    analysis = analyze(to_snapshot(doc))
    assert analysis.candidates[ADMIN_CANDIDATE].state == "unknown"
    assert analysis.high_risk_count == 0 and not analysis.coverage.complete


def test_ac2_passrole_alone_yields_no_finding():
    doc = proposed_doc()
    for fact_id in RULE_B_FACTS[1:]:
        set_state(doc, fact_id, "false")
    analysis = analyze(to_snapshot(doc))
    assert analysis.high_risk_count == 0 and not analysis.potential
    assert analysis.coverage.complete


def test_passrole_alone_with_undeclared_prerequisites_is_inconclusive_not_safe():
    doc = proposed_doc()
    for fact_id in RULE_B_FACTS[1:]:
        remove_fact(doc, fact_id)
    analysis = analyze(to_snapshot(doc))
    assert analysis.high_risk_count == 0
    assert ADMIN_FINDING in analysis.potential
    assert not analysis.coverage.complete


def test_ac4_every_prerequisite_pointer_resolves_to_the_supplied_record():
    doc = proposed_doc()
    analysis = analyze(to_snapshot(doc))
    checked = 0
    for candidate in analysis.candidates.values():
        for p in candidate.prerequisites:
            for ptr in p.pointers:
                value = resolve_pointer(doc, ptr)
                if p.fact_id:
                    assert value["id"] == p.fact_id and value["state"] == p.state
                checked += 1
    assert checked > 20
    for finding in analysis.findings.values():
        assert set(finding.fact_ids) <= set(analysis.snapshot.facts)


def test_ac4_labels_confer_no_privilege():
    doc = proposed_doc()
    for node in doc["nodes"]:
        if node["id"] == RUNTIME_ROLE:
            node["label"] = "AdminRole (AdministratorAccess)"
        if node["id"] == ADMIN_ROLE:
            node["label"] = "harmless read-only role"
    renamed = analyze(to_snapshot(doc))
    original = analyze(to_snapshot(proposed_doc()))
    assert set(renamed.findings) == set(original.findings) == {ADMIN_FINDING}


def test_ac4_unprotected_role_named_admin_is_not_a_finding():
    doc = proposed_doc()
    doc["protected_targets"] = [t for t in doc["protected_targets"] if t["node"] != ADMIN_ROLE]
    analysis = analyze(to_snapshot(doc))
    assert analysis.high_risk_count == 0


def two_route_doc() -> dict:
    """The admin role is reachable through two independent Lambda workloads."""
    return add_workload(proposed_doc(), "l-deploy-hook")


def test_ac6_alternative_route_keeps_the_finding():
    snapshot = to_snapshot(two_route_doc())
    analysis = analyze(snapshot)
    assert ADMIN_FINDING in analysis.findings

    without_first = analyze(snapshot.with_fact_state("f-ci-create-build-hook", "false"))
    assert ADMIN_FINDING in without_first.findings
    witness = without_first.findings[ADMIN_FINDING].witness
    assert [c.via for c in witness] == ["l-deploy-hook"]


def test_ac6_no_effective_single_fix_when_independent_grants_both_enable_access():
    base = baseline_doc()
    # Route 2: the runtime role, reachable today, gains its own path to the admin role.
    for predicate in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code"):
        add_fact(base, f"f-runtime-{predicate}", predicate, RUNTIME_ROLE, "l-build-hook", "true")
    proposal = copy_doc(base)
    set_state(proposal, PASSROLE_FACT, "true")
    set_state(proposal, "f-app-runtime-pass-deploy-admin", "true")
    comparison = compare_snapshots(to_snapshot(base), to_snapshot(proposal))
    assert comparison.deltas[0].id == ADMIN_FINDING and comparison.deltas[0].status == "added"

    fixes = fix_candidates(comparison)
    assert {f.fact_id for f in fixes} == {PASSROLE_FACT, "f-app-runtime-pass-deploy-admin"}
    assert all(ADMIN_FINDING in f.remaining for f in fixes)
    assert best_fix_for(fixes, ADMIN_FINDING) is None


def test_ac6_cycles_terminate_without_duplicate_findings():
    doc = proposed_doc()
    set_state(doc, "f-app-runtime-pass-deploy-admin", "true")
    set_state(doc, "f-deploy-admin-pass-app-runtime", "true")
    for role in (RUNTIME_ROLE, ADMIN_ROLE):
        for predicate in ("lambda_create_function", "lambda_invoke_function", "controls_workload_code"):
            add_fact(doc, f"f-{role}-{predicate}", predicate, role, "l-build-hook", "true")
    analysis = analyze(to_snapshot(doc))
    graph = analysis.established_graph
    assert graph.has_edge(RUNTIME_ROLE, ADMIN_ROLE) and graph.has_edge(ADMIN_ROLE, RUNTIME_ROLE)
    assert list(analysis.findings) == [ADMIN_FINDING]
    assert len(analysis.findings[ADMIN_FINDING].witness) == 1  # the shortest witness wins
    assert analysis.coverage.complete


def test_witness_choice_is_stable_under_ties():
    doc = two_route_doc()
    first = analyze(to_snapshot(doc)).findings[ADMIN_FINDING].witness
    doc["facts"].reverse()
    doc["nodes"].reverse()
    second = analyze(to_snapshot(doc)).findings[ADMIN_FINDING].witness
    assert [c.id for c in first] == [c.id for c in second]
    assert first[0].via == "l-build-hook"  # its fact IDs sort before the l-deploy-hook facts


def test_sensitive_object_read_through_a_role():
    doc = proposed_doc()
    set_state(doc, "f-deploy-admin-read-customer-export", "true")
    analysis = analyze(to_snapshot(doc))
    key = f"finding/{ENTRY}/o-customer-export/sensitive_object_read"
    assert key in analysis.findings
    assert [c.rule for c in analysis.findings[key].witness] == ["lambda_pass_role", "s3_direct_read"]
