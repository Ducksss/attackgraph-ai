"""AC-3 (unknown and unsupported input) and AC-5 (stable comparison)."""

import copy

from helpers import (
    ADMIN_FINDING,
    ENTRY,
    PASSROLE_FACT,
    add_workload,
    baseline_doc,
    proposed_doc,
    read_doc,
    remove_fact,
    set_state,
    to_snapshot,
)

from attackgraph.compare import compare_snapshots
from attackgraph.simulate import best_fix_for, fix_candidates


def compare_docs(base: dict, prop: dict):
    return compare_snapshots(to_snapshot(base, "baseline.json"), to_snapshot(prop, "proposed.json"))


def test_ac3_missing_prerequisite_gives_incomplete_coverage_and_no_verified_fix():
    prop = remove_fact(proposed_doc(), "f-ci-controls-build-hook-code")
    comparison = compare_docs(baseline_doc(), prop)
    assert not comparison.proposal.coverage.complete
    assert comparison.verdict == "incomplete"
    assert all(not d.confirmed for d in comparison.deltas)
    assert best_fix_for(fix_candidates(comparison), ADMIN_FINDING) is None
    reasons = " ".join(i.message for i in comparison.proposal.coverage.issues)
    assert "no fact declares that p-ci-deployer controls the code of l-build-hook" in reasons


def test_ac3_unresolved_policy_control_is_never_a_safe_state():
    base = baseline_doc()
    base["coverage"]["policy_controls"]["service_control_policies"] = "unresolved"
    comparison = compare_docs(base, copy.deepcopy(base))
    assert comparison.deltas == () or all(d.provisional for d in comparison.deltas)
    assert comparison.verdict == "incomplete"
    kinds = {i.kind for i in comparison.baseline.coverage.issues}
    assert "policy_control" in kinds


def test_ac3_unmodelled_mechanism_makes_coverage_incomplete():
    base = baseline_doc()
    base["coverage"]["unmodelled_mechanisms"] = ["general_assume_role"]
    comparison = compare_docs(base, copy.deepcopy(base))
    assert comparison.verdict == "incomplete"


def test_ac3_unknown_to_true_is_inconclusive():
    base = set_state(baseline_doc(), PASSROLE_FACT, "unknown")
    comparison = compare_docs(base, proposed_doc())
    delta = comparison.delta(ADMIN_FINDING)
    assert (delta.baseline_state, delta.proposal_state, delta.status) == ("inconclusive", "reachable", "inconclusive")
    assert not delta.confirmed and comparison.verdict == "incomplete"
    assert best_fix_for(fix_candidates(comparison), ADMIN_FINDING) is None


def test_ac3_true_to_unknown_is_inconclusive():
    prop = set_state(proposed_doc(), PASSROLE_FACT, "unknown")
    comparison = compare_docs(proposed_doc(), prop)
    delta = comparison.delta(ADMIN_FINDING)
    assert (delta.baseline_state, delta.proposal_state, delta.status) == ("reachable", "inconclusive", "inconclusive")
    assert comparison.verdict == "incomplete"


def test_ac3_bundled_unknown_example_is_incomplete():
    comparison = compare_docs(baseline_doc(), read_doc("examples/unknown-prerequisite.json"))
    assert comparison.verdict == "incomplete"
    assert comparison.delta(ADMIN_FINDING).status == "inconclusive"


def test_identical_snapshots_report_no_new_access_with_coverage_retained():
    comparison = compare_docs(baseline_doc(), baseline_doc())
    assert comparison.verdict == "no_new_high_risk"
    assert comparison.deltas == () and comparison.fact_changes == ()
    assert comparison.baseline.coverage.candidate_counts["lambda_pass_role"]["true"] >= 1


def shuffled(doc: dict) -> dict:
    doc = copy.deepcopy(doc)
    for key in ("nodes", "facts", "protected_targets", "expected_access"):
        doc[key].reverse()
    for node in doc["nodes"]:
        node["label"] = node["label"].upper() + " (renamed)"
    return doc


def test_ac5_reordering_and_relabelling_keep_identities_and_counts():
    original = compare_docs(baseline_doc(), proposed_doc())
    reordered = compare_docs(shuffled(baseline_doc()), shuffled(proposed_doc()))
    assert [(d.id, d.status) for d in original.deltas] == [(d.id, d.status) for d in reordered.deltas]
    assert original.proposal.findings[ADMIN_FINDING].fact_ids == reordered.proposal.findings[ADMIN_FINDING].fact_ids
    unchanged = compare_docs(proposed_doc(), shuffled(proposed_doc()))
    assert [(d.status, d.evidence_changed) for d in unchanged.deltas] == [("unchanged", False)]


def test_ac5_removing_an_existing_grant_removes_the_finding():
    prop = set_state(proposed_doc(), "f-deploy-admin-trusts-lambda", "false")
    comparison = compare_docs(proposed_doc(), prop)
    assert [(d.id, d.status, d.confirmed) for d in comparison.deltas] == [(ADMIN_FINDING, "removed", True)]


def test_ac5_changed_evidence_is_unchanged_with_a_flag_and_no_duplicate():
    base = proposed_doc()
    prop = set_state(add_workload(proposed_doc(), "l-deploy-hook"), "f-ci-create-build-hook", "false")
    comparison = compare_docs(base, prop)
    assert len(comparison.deltas) == 1
    delta = comparison.deltas[0]
    assert (delta.status, delta.evidence_changed) == ("unchanged", True)
    assert [c.via for c in delta.proposal.witness] == ["l-deploy-hook"]


def test_ac5_severity_is_high_for_every_status():
    added = compare_docs(baseline_doc(), proposed_doc()).deltas
    removed = compare_docs(proposed_doc(), baseline_doc()).deltas
    unchanged = compare_docs(proposed_doc(), proposed_doc()).deltas
    inconclusive = compare_docs(baseline_doc(), read_doc("examples/unknown-prerequisite.json")).deltas
    statuses = {d.status: d.severity for d in (*added, *removed, *unchanged, *inconclusive)}
    assert statuses == {"added": "High", "removed": "High", "unchanged": "High", "inconclusive": "High"}


def test_ac5_ordinary_access_is_informational_only():
    comparison = compare_docs(baseline_doc(), proposed_doc())
    findings_targets = {d.target for d in comparison.deltas}
    assert "o-build-artifacts" not in findings_targets and "r-app-runtime" not in findings_targets
    results = {r.check.id: r.result for r in comparison.proposal.expected_access}
    assert results == {"ea-ci-reads-build-artifacts": "pass", "ea-ci-deploys-app-runtime": "pass"}


def test_target_sensitivity_change_is_a_visible_configuration_change():
    base = proposed_doc()
    base["protected_targets"] = [t for t in base["protected_targets"] if t["node"] != "r-deploy-admin"]
    comparison = compare_docs(base, proposed_doc())
    assert comparison.delta(ADMIN_FINDING).status == "added"
    changes = [(c.kind, c.subject, c.before, c.after) for c in comparison.config_changes]
    assert ("target_classification", "r-deploy-admin", "not protected", "privileged_role") in changes
    assert comparison.delta(ADMIN_FINDING).baseline_state == "out_of_scope"


def test_fact_changes_record_before_and_after_states():
    comparison = compare_docs(baseline_doc(), proposed_doc())
    assert [(c.fact_id, c.before, c.after, c.newly_enabled) for c in comparison.fact_changes] == [
        (PASSROLE_FACT, "false", "true", True)
    ]
    assert comparison.fact_changes[0].proposal.pointer == "/facts/1"
    assert ENTRY in comparison.fact_changes[0].describe()
