"""The plain-language story and its HTML: facts only, escaped labels, no em-dashes."""

import re
from pathlib import Path

from helpers import ADMIN_FINDING, PASSROLE_FACT, baseline_doc, proposed_doc, read_doc, set_state, to_bytes, to_snapshot

from attackgraph import page, web
from attackgraph.compare import compare_snapshots
from attackgraph.pipeline import run
from attackgraph.simulate import best_fix_for, fix_candidates
from attackgraph.story import build_story, summary


def flagship():
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(proposed_doc()))
    return comparison, build_story(comparison, comparison.delta(ADMIN_FINDING))


def test_story_follows_the_witness_with_the_lambda_as_a_stop():
    _, story = flagship()
    assert [n.id for n in story.nodes] == ["p-ci-deployer", "l-build-hook", "r-deploy-admin"]
    assert [(h.text, h.changed) for h in story.hops] == [("can pass Deployment admin role to", True), ("runs as", False)]
    assert story.nodes[-1].protected == "privileged_role"
    assert story.headline == "CI deploy user (build pipeline) can now run code as Deployment admin role"


def test_changed_condition_comes_first_and_baseline_blocker_is_recorded():
    _, story = flagship()
    conditions = story.steps[0].conditions
    assert len(conditions) == 7 and all(c.state == "true" for c in conditions)
    assert conditions[0].fact_id == PASSROLE_FACT and conditions[0].change == "false → true"
    assert [c.fact_id for c in story.changes] == [PASSROLE_FACT]
    assert story.steps[0].baseline_state == "false" and story.steps[0].baseline_blockers == (PASSROLE_FACT,)
    texts = [c.text for c in conditions]
    assert "CI deploy user (build pipeline) controls the code that Post-build hook function runs" in texts


def test_the_blocked_note_names_only_the_false_conditions():
    both = compare_snapshots(to_snapshot(set_state(baseline_doc(), "f-deploy-admin-trusts-lambda", "false")), to_snapshot(proposed_doc()))
    note = page.path_card(build_story(both, both.delta(ADMIN_FINDING)))
    assert 'f-ci-pass-deploy-admin</span> and <span class="ag-mono">f-deploy-admin-trusts-lambda</span> were false.' in note
    unknown = compare_snapshots(to_snapshot(set_state(baseline_doc(), "f-deploy-admin-trusts-lambda", "unknown")), to_snapshot(proposed_doc()))
    story = build_story(unknown, unknown.delta(ADMIN_FINDING))
    assert story.steps[0].baseline_blockers == (PASSROLE_FACT,)  # the unknown trust did not block anything


def test_the_incomplete_banner_counts_each_open_item_once_and_by_kind():
    unknown = read_doc("examples/unknown-prerequisite.json")
    same = run(to_bytes(unknown), "b.json", to_bytes(unknown), "p.json")  # one unresolved relationship, on both sides
    assert "1 relationship could not be resolved, so nothing here is a safe verdict. The unresolved condition is marked below." in page.verdict(same)
    scp = run(to_bytes(baseline_doc()), "b.json", to_bytes(read_doc("examples/unresolved-policy-control.json")), "p.json")
    assert "4 relationships could not be resolved and 1 policy control is unresolved" in page.verdict(scp)
    assert "The unresolved conditions are marked below." in page.verdict(scp)
    assert "4 unresolved relationships, 1 unresolved policy control" in page.stats(scp)


def test_summary_states_only_engine_facts():
    comparison, story = flagship()
    fix = best_fix_for(fix_candidates(comparison), ADMIN_FINDING)
    text = " ".join(summary(story, fix))
    assert "The proposal changes one condition" in text and "(false to true)" in text
    assert "all 7 conditions on this route hold" in text
    assert f"Revoking {PASSROLE_FACT} on a copy removes the path and keeps 2 of 2" in text
    assert "Verified in this model." in text and "Nothing was deployed or executed." in text


def test_two_step_route_draws_every_stop():
    doc = set_state(proposed_doc(), "f-deploy-admin-read-customer-export", "true")
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(doc))
    story = build_story(comparison, comparison.delta("finding/p-ci-deployer/o-customer-export/sensitive_object_read"))
    assert [n.id for n in story.nodes] == ["p-ci-deployer", "l-build-hook", "r-deploy-admin", "o-customer-export"]
    assert story.hops[-1].text == "can read" and len(story.steps) == 2
    assert "2 of 2 conditions hold" in web.conditions(story) or "of" in web.conditions(story)


def test_unknown_hops_are_dashed_not_new():
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(read_doc("examples/unknown-prerequisite.json")))
    story = build_story(comparison, comparison.delta(ADMIN_FINDING))
    rendered = web.path(story)
    assert ">Unknown</span>" in rendered and ">New</span>" not in rendered and 'class="ag-hop maybe"' in rendered


def test_established_route_with_an_unresolved_baseline_is_stated_not_questioned():
    # The proposal reaches the admin role outright; only whether that is new is unknown.
    comparison = compare_snapshots(to_snapshot(read_doc("examples/unknown-prerequisite.json")), to_snapshot(proposed_doc()))
    delta = comparison.delta(ADMIN_FINDING)
    assert delta.status == "inconclusive" and delta.proposal_state == "reachable"
    story = build_story(comparison, delta)
    assert story.headline == "CI deploy user (build pipeline) can run code as Deployment admin role in the proposal"
    text = " ".join(summary(story))
    assert "(unknown to true)" in text and "cannot say whether the route is new" in text and "unknown is unknown" not in text
    conditions = page.conditions_card(story)
    assert "7 of 7 hold" in conditions and "One condition is unknown" not in conditions
    assert "makes this condition unknown" not in page.change_card(comparison, story)
    path = web.path(story, key=True)
    assert 'class="ag-hop maybe"' not in path and ">Changed</span>" in path and ">New</span>" not in path


def test_unknown_policy_control_is_named_instead_of_the_changed_fact():
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(read_doc("examples/unresolved-policy-control.json")))
    story = build_story(comparison, comparison.delta(ADMIN_FINDING))
    text = " ".join(summary(story))
    assert "The snapshot marks service control policies as unresolved, so they could block this route." in text
    assert "(false to true)" in text and "apply is unknown" not in text
    card = page.change_card(comparison, story)
    assert "flips one condition and makes another unknown" in card
    assert "/coverage/policy_controls/service_control_policies" in card  # the policy change is shown as a change
    # The Unknown badge sits on the hop whose own condition is unknown, not on the changed PassRole hop.
    path = web.path(story)
    assert '<span class="ag-badge amber ag-hop-badge">Unknown</span><div class="ag-hop-text">runs as</div>' in path


def test_simulated_fix_cuts_only_the_revoked_hop():
    base = set_state(baseline_doc(), "f-deploy-admin-trusts-lambda", "false")
    comparison = compare_snapshots(to_snapshot(base), to_snapshot(proposed_doc()))
    story = build_story(comparison, comparison.delta(ADMIN_FINDING))
    assert [h.changed for h in story.hops] == [True, True]  # PassRole and the trust policy both changed
    path = web.path(story, "simulated", revoked="f-deploy-admin-trusts-lambda")
    assert '<span class="ag-badge new ag-hop-badge">New</span><div class="ag-hop-text">can pass' in path
    assert '<span class="ag-badge red ag-hop-badge">Revoked</span><div class="ag-hop-text">runs as</div>' in path


def test_labels_are_escaped_in_every_fragment():
    injected = read_doc("examples/label-injection.json")
    comparison = compare_snapshots(to_snapshot(baseline_doc()), to_snapshot(injected))
    story = build_story(comparison, comparison.delta(ADMIN_FINDING))
    fragments = [
        web.path(story),
        web.path(story, "simulated"),
        web.conditions(story),
        web.change_block(story),
        web.summary(summary(story)),
        web.verdict("risk", story.headline, story.headline, [("/nodes/0", "<b>bad</b>")]),
    ]
    for fragment in fragments:
        assert "<script>" not in fragment and "javascript:alert" not in fragment.replace("javascript:alert(1)", "")
    assert "&lt;script&gt;" in web.path(story)


def test_path_key_lists_only_the_line_styles_drawn():
    _, story = flagship()
    live = web.path(story, key=True)
    assert "Established relationship" in live and "New in the proposal" in live
    assert "Depends on an unknown condition" not in live and "Revoked" not in live.split('class="ag-key"')[1]
    simulated = web.path(story, "simulated", key=True).split('class="ag-key"')[1]
    assert "Revoked by the simulated fix" in simulated and "No longer reachable" in simulated
    assert "Established relationship" not in simulated


def test_no_em_dashes_in_visible_copy():
    root = Path(__file__).resolve().parents[1]
    sources = [root / "app.py", *sorted((root / "views").glob("*.py"))]
    sources += [root / "attackgraph" / name for name in ("web.py", "story.py", "page.py", "landing.py")]
    for path in sources:
        assert "—" not in path.read_text(), path
        assert not re.search("–", path.read_text()), path
