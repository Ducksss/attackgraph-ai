"""AC-7: the fix simulation, its ranking and immutability of the inputs."""

import hashlib

from helpers import (
    ADMIN_FINDING,
    FIXTURES,
    PASSROLE_FACT,
    baseline_doc,
    proposed_doc,
    set_state,
    to_snapshot,
)

from attackgraph.compare import compare_snapshots
from attackgraph.pipeline import run
from attackgraph.simulate import best_fix_for, fix_candidates


def demo_run():
    base = (FIXTURES / "demo" / "baseline.json").read_bytes()
    prop = (FIXTURES / "demo" / "proposed.json").read_bytes()
    return base, prop, run(base, "baseline.json", prop, "proposed.json")


def test_ac7_verified_fix_preserves_expected_access_and_leaves_inputs_untouched():
    base_bytes, prop_bytes, result = demo_run()
    digests = (hashlib.sha256(base_bytes).hexdigest(), hashlib.sha256(prop_bytes).hexdigest())

    fix = best_fix_for(result.fixes, ADMIN_FINDING)
    assert fix.verified_for(ADMIN_FINDING) and fix.rank == 1
    assert fix.removed == (ADMIN_FINDING,) and fix.remaining == () and fix.now_inconclusive == ()
    after = {r.check.id: r.result for r in fix.expected_after}
    assert after == {"ea-ci-reads-build-artifacts": "pass", "ea-ci-deploys-app-runtime": "pass"}
    assert fix.expected_changes == ()

    # The record is kept with its provenance; only the state changes.
    revoked = fix.simulated.snapshot.facts[PASSROLE_FACT]
    assert (revoked.state, revoked.pointer) == ("false", "/facts/1")
    assert fix.simulated.snapshot.revisions[0].from_state == "true"

    # Reset: the proposal analysis and the uploaded bytes are unchanged.
    assert result.comparison.proposal.snapshot.facts[PASSROLE_FACT].state == "true"
    assert result.comparison.proposal.high_risk_count == 1
    assert digests == (
        hashlib.sha256((FIXTURES / "demo" / "baseline.json").read_bytes()).hexdigest(),
        hashlib.sha256((FIXTURES / "demo" / "proposed.json").read_bytes()).hexdigest(),
    )
    assert result.comparison.proposal.snapshot.sha256 == digests[1]


def test_fix_ranking_prefers_preserved_expected_access():
    base = set_state(baseline_doc(), "f-ci-create-build-hook", "false")
    prop = set_state(proposed_doc(), "f-ci-create-build-hook", "true")
    comparison = compare_snapshots(to_snapshot(base), to_snapshot(prop))
    fixes = fix_candidates(comparison)
    assert [(f.fact_id, f.rank, f.failed_expected) for f in fixes] == [
        (PASSROLE_FACT, 1, 0),
        ("f-ci-create-build-hook", 2, 1),
    ]
    collateral = fixes[1].expected_changes
    assert collateral == (("ea-ci-deploys-app-runtime", "pass", "fail"),)
    assert best_fix_for(fixes, ADMIN_FINDING).fact_id == PASSROLE_FACT


def test_scenario_assumptions_are_not_offered_as_fixes():
    base = set_state(baseline_doc(), "f-ci-controls-build-hook-code", "false")
    prop = set_state(proposed_doc(), "f-ci-controls-build-hook-code", "true")
    comparison = compare_snapshots(to_snapshot(base), to_snapshot(prop))
    assert "f-ci-controls-build-hook-code" not in {f.fact_id for f in fix_candidates(comparison)}


def test_no_fix_candidates_when_access_already_existed():
    comparison = compare_snapshots(to_snapshot(proposed_doc()), to_snapshot(proposed_doc()))
    assert fix_candidates(comparison) == ()


def test_bundled_scenario_meets_the_two_second_target():
    import time

    started = time.perf_counter()
    for _ in range(5):
        demo_run()
    assert (time.perf_counter() - started) / 5 < 2.0
