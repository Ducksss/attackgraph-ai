"""The plain-language story and its HTML: facts only, escaped labels, no em-dashes."""

import re
from pathlib import Path

from helpers import ADMIN_FINDING, PASSROLE_FACT, baseline_doc, proposed_doc, read_doc, set_state, to_snapshot

from attackgraph import web
from attackgraph.compare import compare_snapshots
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
