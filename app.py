"""AttackGraph AI: judge-facing Streamlit page.

Run with: streamlit run app.py
Deep link a scenario with ?scenario=passrole|repair|unknown|invalid|upload.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import streamlit as st

from attackgraph import ENGINE_VERSION, MODEL_VERSION, web
from attackgraph.analysis import RULE_TITLES, Finding
from attackgraph.explain import (
    TIMEOUT_SECONDS,
    BedrockExplainer,
    ai_enabled,
    build_packet,
    configured_model,
    is_current,
)
from attackgraph.pipeline import PipelineResult, run
from attackgraph.render import md_escape, md_segments, step_text, witness_dot
from attackgraph.report import build_report
from attackgraph.simulate import best_fix_for
from attackgraph.snapshot import MAX_BYTES, POLICY_CONTROLS, UNMODELLED_MECHANISMS
from attackgraph.story import build_story, expected_text, involves_pass_role, is_potential, summary

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
SCENARIOS = {
    "passrole": ("PassRole change", "demo/baseline.json", "demo/proposed.json"),
    "repair": ("Proposed vs repaired", "demo/proposed.json", "demo/repaired.json"),
    "unknown": ("Unknown fact", "demo/baseline.json", "examples/unknown-prerequisite.json"),
    "invalid": ("Invalid file", "demo/baseline.json", "examples/invalid-references.json"),
}
UPLOAD = "upload"
SCENARIO_LABELS = {**{key: value[0] for key, value in SCENARIOS.items()}, UPLOAD: "Upload your own"}
STATUS_BADGES = {"added": "amber", "removed": "green", "unchanged": "gray", "inconclusive": "amber"}
STATUS_WORDS = {"added": "New path", "removed": "Path closed", "unchanged": "Unchanged", "inconclusive": "Unresolved"}
STATE_BADGE = {"true": ":blue-badge[true]", "false": ":gray-badge[false]", "unknown": ":orange-badge[unknown]"}
RESULT_BADGE = {"pass": ":green-badge[pass]", "fail": ":red-badge[fail]", "inconclusive": ":orange-badge[inconclusive]"}
REASONS = {"invalid": "reply rejected", "refused": "model declined", "timeout": "timed out", "disabled": "turned off"}


def code(value: str) -> str:
    return f"`{value}`"


def model_name(model_id: str) -> str:
    names = {"nova-pro": "Amazon Nova Pro", "nova-lite": "Amazon Nova Lite", "nova-2-lite": "Amazon Nova 2 Lite", "claude": "Claude"}
    return next((name for key, name in names.items() if key in model_id), model_id)


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def init_state() -> None:
    for key, value in {
        "result": None,
        "loaded": None,
        "simulation": None,
        "explanations": {},
        "uploader_nonce": 0,
        "explainer": None,
    }.items():
        st.session_state.setdefault(key, value)
    if "scenario" not in st.session_state:
        requested = st.query_params.get("scenario", "passrole")
        st.session_state.scenario = requested if requested in SCENARIO_LABELS else "passrole"


def sync_scenario() -> None:
    """Bundled scenarios run as soon as they are picked; uploads wait for both files."""
    scenario = st.session_state.scenario
    if scenario == UPLOAD:
        if not st.session_state.loaded or st.session_state.loaded[0] != UPLOAD:
            st.session_state.result, st.session_state.loaded, st.session_state.simulation = None, (UPLOAD, None), None
        return
    if st.session_state.loaded != ("scenario", scenario):
        _, baseline, proposal = SCENARIOS[scenario]
        st.session_state.result = run(
            (FIXTURES / baseline).read_bytes(), Path(baseline).name, (FIXTURES / proposal).read_bytes(), Path(proposal).name
        )
        st.session_state.loaded = ("scenario", scenario)
        st.session_state.simulation = None


def reset_app() -> None:
    nonce = st.session_state.get("uploader_nonce", 0) + 1
    st.session_state.clear()
    st.session_state.uploader_nonce = nonce


@st.cache_resource
def flagship() -> PipelineResult:
    _, baseline, proposal = SCENARIOS["passrole"]
    return run((FIXTURES / baseline).read_bytes(), "baseline.json", (FIXTURES / proposal).read_bytes(), "proposed.json")


def hero_preview() -> str:
    comparison = flagship().comparison
    return web.path(build_story(comparison, comparison.deltas[0]), compact=True)


def explainer() -> BedrockExplainer:
    model_id, region = configured_model()
    current = st.session_state.explainer
    if current is None or (current.model_id, current.region) != (model_id, region):
        current = st.session_state.explainer = BedrockExplainer(model_id, region)
    return current


def active_simulation(result: PipelineResult):
    sim = st.session_state.simulation
    if not sim or sim["analysis_id"] != result.comparison.analysis_id:
        return None
    return next((f for f in result.fixes if f.id == sim["fix_id"]), None)


def start_simulation(analysis_id: str, fix_id: str) -> None:
    st.session_state.simulation = {"analysis_id": analysis_id, "fix_id": fix_id}


def stop_simulation() -> None:
    st.session_state.simulation = None


def upload_panel() -> None:
    nonce = st.session_state.uploader_nonce
    left, right = st.columns(2)
    baseline = left.file_uploader("Baseline snapshot (JSON)", type=["json"], key=f"up-b-{nonce}", max_upload_size=2)
    proposal = right.file_uploader("Proposed snapshot (JSON)", type=["json"], key=f"up-p-{nonce}", max_upload_size=2)
    st.caption(f"Each file must follow the snapshot schema and be at most {MAX_BYTES // 1024:,} KiB. Start from the bundled fixtures.")
    with st.expander("Snapshot format and rules"):
        schema_help()
    if baseline and proposal:
        b, p = baseline.getvalue(), proposal.getvalue()
        signature = (baseline.name, hashlib.sha256(b).hexdigest(), proposal.name, hashlib.sha256(p).hexdigest())
        if st.session_state.loaded != (UPLOAD, signature):
            st.session_state.result = run(b, baseline.name, p, proposal.name)
            st.session_state.loaded, st.session_state.simulation = (UPLOAD, signature), None


def schema_help() -> None:
    st.markdown(
        "Snapshots are hand-authored **synthetic** JSON, not Terraform or raw IAM policies. Labels are display text "
        f"only. The full schema is {code('attackgraph/snapshot.schema.json')} and the demo fixtures are in "
        f"{code('fixtures/demo/')}.\n\n"
        f"- **{RULE_TITLES['s3_direct_read']}.** A declared effective `s3:GetObject` fact for that exact object.\n"
        f"- **{RULE_TITLES['lambda_pass_role']}.** Pass the role to Lambda, create and invoke the function, control its "
        "code, the role trusts Lambda, one account, and no unresolved policy restrictions. All must be true.\n"
        "- A condition with no declared fact is `unknown`, and any unknown makes the analysis incomplete."
    )


def invalid_state(result: PipelineResult) -> None:
    errors = [
        (f"{loaded.source_name} {issue.pointer or '(file)'}", issue.message)
        for loaded in (result.baseline, result.proposal)
        for issue in loaded.issues
    ]
    st.html(
        web.verdict(
            "error",
            "These files can't be analysed yet",
            f"{plural(len(errors), 'field error')} found. Neither file is analysed until both are valid.",
            errors,
        )
    )


def verdict_block(result: PipelineResult) -> None:
    comparison = result.comparison
    added = [d for d in comparison.deltas if d.status == "added"]
    removed = comparison.count("removed")
    if comparison.verdict == "incomplete":
        unresolved = len(comparison.baseline.coverage.issues) + len(comparison.proposal.coverage.issues)
        st.html(
            web.verdict(
                "unknown",
                "Analysis incomplete",
                f"{plural(unresolved, 'relationship')} could not be resolved, so nothing here is a safe verdict. "
                "The unresolved condition is marked below.",
            )
        )
    elif added:
        kinds = {d.impact for d in added}
        target = "role" if kinds == {"privileged_role_use"} else "data" if kinds == {"sensitive_object_read"} else "resource"
        first = build_story(comparison, added[0])
        st.html(
            web.verdict(
                "risk",
                f"{plural(len(added), 'new path')} to a protected {target}",
                f"{first.headline}. Nothing was deployed: this is a static check of two synthetic snapshots.",
            )
        )
    elif removed:
        st.html(
            web.verdict(
                "safe",
                f"The change closes {plural(removed, 'path')} and opens none",
                "Every relationship resolved. Complete for the declared synthetic model, not for a real AWS account.",
            )
        )
    else:
        st.html(
            web.verdict(
                "safe",
                "No new paths to protected resources",
                "Every relationship resolved. Complete for the declared synthetic model, not for a real AWS account.",
            )
        )


def stats_block(result: PipelineResult) -> None:
    comparison = result.comparison
    sim = active_simulation(result)
    added = [d for d in comparison.deltas if d.status == "added"]
    before, after = comparison.baseline.high_risk_count, comparison.proposal.high_risk_count
    risk_note = f"Baseline {before}, proposed {after}"
    if sim:
        risk_note += f", after simulated fix {sim.simulated.high_risk_count}"
    unresolved = len(comparison.proposal.coverage.issues) + len(comparison.baseline.coverage.issues)
    fix = best_fix_for(result.fixes, added[0].id) if added else None
    if not comparison.complete:
        fix_value, fix_note, fix_tone = "Not yet", "A fix cannot be verified while a condition is unknown", ""
    elif fix:
        kept = sum(1 for r in fix.expected_after if r.result == "pass")
        fix_value, fix_note, fix_tone = "1 revocation", f"Normal access kept: {kept} of {len(fix.expected_after)}", "good"
    elif added:
        fix_value, fix_note, fix_tone = "None found", "No single revocation closes the path", "risk"
    else:
        fix_value, fix_note, fix_tone = "Not needed", "No new path to fix", ""
    first_change = comparison.fact_changes[0].fact_id if comparison.fact_changes else "No fact changed"
    st.html(
        web.stats(
            [
                ("Facts changed", str(len(comparison.fact_changes)), first_change, ""),
                (
                    "New risky paths",
                    str(len(added)) if comparison.complete else f"{len(added)} confirmed",
                    risk_note if comparison.complete else f"{risk_note}; unresolved paths are not counted",
                    "risk" if added else "good" if comparison.complete else "",
                ),
                (
                    "Coverage",
                    "Complete" if comparison.complete else "Incomplete",
                    "Every relationship resolved" if comparison.complete else f"{plural(unresolved, 'unresolved relationship')}",
                    "good" if comparison.complete else "risk",
                ),
                ("Verified fix", fix_value, fix_note, fix_tone),
            ]
        )
    )


def choose_finding(comparison):
    deltas = comparison.deltas
    if not deltas:
        return None
    if len(deltas) == 1:
        return deltas[0]
    key = st.selectbox(
        "Finding to walk through",
        [d.id for d in deltas],
        format_func=lambda k: f"{STATUS_WORDS[comparison.delta(k).status]}: {build_story(comparison, comparison.delta(k)).headline}",
        key=f"finding-{comparison.analysis_id}",
    )
    return comparison.delta(key)


def change_card(comparison, story) -> None:
    delta = story.delta
    badge = f'<span class="ag-badge {STATUS_BADGES[delta.status]}">{web.esc(STATUS_WORDS[delta.status])}</span>'
    other = len(comparison.fact_changes) - len(story.changes)
    extra = f'<p class="ag-note">{plural(other, "other fact")} also changed; see the evidence below.</p>' if other > 0 else ""
    intro = {
        "added": "The proposal flips this condition. Nothing else on the route changed.",
        "removed": "The second snapshot flips this condition back.",
        "unchanged": "The route exists in both snapshots.",
        "inconclusive": "The proposal makes this condition unknown, so the engine cannot decide.",
    }[delta.status]
    if delta.status == "added" and len(story.changes) > 1:
        intro = "The proposal flips these conditions."
    glossary = web.PASSROLE_GLOSSARY if involves_pass_role(story) else ""
    with st.container(key="agcard-change"):
        st.html(
            web.card_head("difference", "The change", badge)
            + f'<p class="ag-note">{web.esc(intro)}</p>'
            + web.change_block(story)
            + extra
            + glossary
        )


def path_card(result: PipelineResult, story) -> None:
    delta = story.delta
    sim = active_simulation(result)
    title = {
        "added": "The path it opens",
        "removed": "The path it closes",
        "unchanged": "A path in both snapshots",
        "inconclusive": "A possible path, not established",
    }[delta.status]
    mode = "simulated" if sim and sim.removes(delta.id) else "closed" if delta.status == "removed" else "live"
    target = "role" if delta.impact == "privileged_role_use" else "data"
    if mode == "simulated":
        title = "The path, closed by the simulated fix"
        note = f"{sim.fact_id} is revoked on a copy of the proposal. The route no longer reaches the protected {target}."
    elif delta.status == "added":
        note = f"{story.headline}. Follow the arrows: each one is an established relationship."
    elif delta.status == "inconclusive":
        note = "A dashed arrow depends on an unknown condition, so this is not a finding and not safe either."
    elif delta.status == "removed":
        note = f"{story.headline}. The red arrow is the relationship the second snapshot removes."
    else:
        note = f"{story.headline}."
    blocked = ""
    if delta.status == "added" and all(step.baseline_state == "false" for step in story.steps):
        ids = sorted({b for step in story.steps for b in step.baseline_blockers})
        blocked = (
            '<p class="ag-note">In the baseline the same route was blocked because '
            + ", ".join(f'<span class="ag-mono">{web.esc(i)}</span>' for i in ids)
            + " was false.</p>"
        )
    with st.container(key="agcard-path"):
        st.html(
            web.card_head("conversion_path", title)
            + f'<p class="ag-note">{web.esc(note)}</p>'
            + web.path(story, mode)
            + blocked
        )


def conditions_card(story) -> None:
    held = sum(1 for c in story.conditions if c.state == "true")
    status = story.delta.status
    title, lead = {
        "added": ("Why the route works", "A route only counts when every condition holds. The changed one was the missing piece."),
        "unchanged": ("Why the route works", "A route only counts when every condition holds."),
        "removed": ("What the route needed", "Every condition held in the first snapshot. The second one takes away the changed one."),
        "inconclusive": ("What is unresolved", "One condition is unknown, so the engine will not call this route open or closed."),
    }[status]
    with st.container(key="agcard-conds"):
        st.html(
            web.card_head("checklist", title, f'<span class="ag-badge gray">{held} of {len(story.conditions)} hold</span>')
            + f'<p class="ag-note">{web.esc(lead)}</p>'
            + web.conditions(story)
        )


def ai_card(result: PipelineResult, delta, story) -> None:
    comparison = result.comparison
    model_id, region = configured_model()
    key = (comparison.analysis_id, delta.id)
    stored = st.session_state.explanations.get(key)
    if stored is not None and not is_current(stored, comparison.analysis_id):
        stored = None
    packet = build_packet(comparison, delta, result.fixes)
    enabled = ai_enabled()
    with st.container(key="agcard-ai"):
        st.html(
            web.card_head("auto_awesome", "Why it matters", '<span class="ag-badge green">Amazon Bedrock</span>')
            + f'<p class="ag-note">{web.esc(model_name(model_id))} explains the evidence in plain English. It sees '
            "placeholder IDs only and cannot change the result.</p>"
        )
        if st.button(
            "Explain with Amazon Bedrock",
            type="primary",
            icon=":material/auto_awesome:",
            disabled=not enabled,
            help=f"One Converse call to {model_id} in {region}, {TIMEOUT_SECONDS} s timeout."
            if enabled
            else "AI explanations are turned off (ATTACKGRAPH_AI=off).",
            key=f"explain-{delta.id}",
        ):
            with st.spinner(f"Asking {model_id}..."):
                outcome = explainer().explain(packet)
            if is_current(outcome, comparison.analysis_id):
                st.session_state.explanations[key] = outcome
                stored = outcome
        fix = next((f for f in result.fixes if f.removes(delta.id)), None)
        plain = web.summary(summary(story, fix))
        if stored is None:
            st.markdown(":gray-badge[Deterministic summary, not AI-generated]")
            st.html(plain)
        elif stored.ok:
            meta = [f"{stored.model_id}", stored.region]
            if stored.request_id:
                meta.append(f"request {stored.request_id}")
            if stored.input_tokens is not None:
                meta.append(f"{stored.input_tokens:,} in, {stored.output_tokens:,} out tokens")
            if stored.latency_ms is not None:
                meta.append(f"{stored.latency_ms / 1000:.1f} s")
            cached = " :gray-badge[cached: no new call]" if stored.cached else ""
            st.markdown(f":green-badge[AI explanation]{cached}  \n:small[{md_escape(', '.join(meta))}]")
            st.markdown(md_segments(stored.summary))
            st.markdown(f":small[**Limitations:** {md_segments(stored.limitations)}]")
            with st.expander("Deterministic summary for comparison"):
                st.html(plain)
        else:
            reason = "" if stored.status == "unavailable" else f" ({REASONS.get(stored.status, stored.status)})"
            st.warning(f"**AI explanation unavailable**{reason}. {md_escape(stored.error)}", icon=":material/cloud_off:")
            st.markdown(":gray-badge[Deterministic summary, not AI-generated]")
            st.html(plain)
        with st.expander("What the model sees"):
            st.caption("The complete evidence packet sent to Bedrock. Every name is a placeholder; the page maps them back.")
            st.code(json.dumps(packet.payload, indent=1), language="json")


def fix_card(result: PipelineResult, delta, story) -> None:
    comparison = result.comparison
    sim = active_simulation(result)
    with st.container(key="agcard-fix"):
        st.html(web.card_head("healing", "The fix"))
        if delta.proposal is None:
            st.html('<p class="ag-note">This path only exists in the first snapshot, so there is nothing to fix.</p>')
            return
        if is_potential(delta) or delta.status == "inconclusive":
            st.html(
                '<p class="ag-note">No fix can be verified while a condition is unknown. Declare the fact as true or '
                "false, then compare again.</p>"
            )
            return
        if not result.fixes:
            reason = "The access already existed in the baseline." if delta.status == "unchanged" else "No newly enabled grant is on this route."
            st.html(f'<p class="ag-note">No single-permission fix to test. {web.esc(reason)}</p>')
            return
        best = best_fix_for(result.fixes, delta.id)
        options = [f.id for f in result.fixes]
        chosen = best or result.fixes[0]
        if len(options) > 1:
            pick = st.radio(
                "Revocations the engine tested",
                options,
                index=options.index(chosen.id),
                format_func=lambda fid: next(f for f in result.fixes if f.id == fid).fact_id,
                key=f"fix-{comparison.analysis_id}-{delta.id}",
                horizontal=True,
            )
            chosen = next(f for f in result.fixes if f.id == pick)
        story_fact = next((c for c in story.conditions if c.fact_id == chosen.fact_id), None)
        human = story_fact.text if story_fact else chosen.proposal_fact.describe()
        if best is None:
            st.html(
                '<p class="ag-note">No single revocation closes this path: another route remains after each one.</p>'
            )
        st.html(
            f'<p class="ag-note">Revoke <span class="ag-mono">{web.esc(chosen.fact_id)}</span> '
            f"({web.esc(human)}) on an in-memory copy of the proposal, then rerun the whole analysis.</p>"
        )
        buttons = st.container(horizontal=True)
        buttons.button(
            "Simulate the fix",
            type="primary",
            icon=":material/science:",
            on_click=start_simulation,
            args=(comparison.analysis_id, chosen.id),
            key=f"simulate-{delta.id}",
        )
        snapshot = comparison.proposal.snapshot
        rows = []
        for row in comparison.proposal.expected_access:
            after = sim.simulated.expected_result(row.check.id) if sim else None
            rows.append((expected_text(row.check, snapshot), row.result, after.result if after else None))
        if rows:
            st.html('<p class="ag-note" style="margin-top:14px">Normal access the fix must keep:</p>' + web.expected_list(rows))
        if sim is not None:
            buttons.button("Reset simulation", on_click=stop_simulation, key=f"reset-sim-{delta.id}")
            kept = sum(1 for r in sim.expected_after if r.result == "pass")
            verified = sim.verified_for(delta.id)
            st.html(
                web.stats(
                    [
                        (
                            "High-risk paths",
                            f"{comparison.proposal.high_risk_count} → {sim.simulated.high_risk_count}",
                            "Proposed, then after the fix",
                            "good" if not sim.remaining else "risk",
                        ),
                        (
                            "Normal access",
                            f"{kept} of {len(sim.expected_after)}",
                            "Expected-access checks that still pass",
                            "good" if kept == len(sim.expected_after) else "risk",
                        ),
                    ],
                    columns=2,
                )
                + (
                    '<p class="ag-note"><span class="ag-badge green">Verified in this model</span> The path is gone and '
                    "every relationship stayed resolved. The uploaded files are unchanged.</p>"
                    if verified
                    else '<p class="ag-note"><span class="ag-badge amber">Not verified</span> The finding remains, or '
                    "coverage became incomplete after the change.</p>"
                )
            )


def prerequisite_table(candidate, comparison) -> str:
    rows = ["| State | Condition | Evidence | JSON pointer |", "|---|---|---|---|"]
    for p in candidate.prerequisites:
        evidence = code(p.fact_id) if p.fact_id else ("not declared" if p.origin == "missing" else "derived")
        change = comparison.fact_change(p.fact_id) if p.fact_id else None
        if change is not None:
            evidence += f" :orange-badge[changed {change.before} → {change.after}]"
        if p.assumption:
            evidence += " :gray-badge[scenario assumption]"
        note = f" ({md_escape(p.note)})" if p.note and p.state != "true" else ""
        pointers = ", ".join(code(ptr) for ptr in p.pointers) or "-"
        rows.append(f"| {STATE_BADGE[p.state]} | {md_escape(p.text)}{note} | {evidence} | {pointers} |")
    return "\n".join(rows)


def coverage_row(label: str, analysis) -> str:
    cov = analysis.coverage
    rules = [
        f"{c['true']} established, {c['false']} blocked, {c['unknown']} unresolved"
        for c in (cov.candidate_counts["s3_direct_read"], cov.candidate_counts["lambda_pass_role"])
    ]
    unresolved = [POLICY_CONTROLS[k].lower() for k, v in analysis.snapshot.policy_controls.items() if v != "resolved"]
    policy = "all 5 resolved" if not unresolved else ":orange-badge[unresolved] " + ", ".join(unresolved)
    mechanisms = ", ".join(UNMODELLED_MECHANISMS[m] for m in analysis.snapshot.unmodelled_mechanisms) or "none"
    badge = ":green-badge[complete]" if cov.complete else ":orange-badge[incomplete]"
    return f"| {label} | {badge} | {rules[0]} | {rules[1]} | {policy} | {md_escape(mechanisms)} |"


def evidence_section(result: PipelineResult, delta) -> None:
    comparison = result.comparison
    sim = active_simulation(result)
    with st.expander("Evidence for reviewers: every condition, pointer and check"):
        tabs = st.tabs(["Conditions", "Coverage", "All changes", "Normal access", "Graph", "Report"])
        with tabs[0]:
            if delta is None:
                st.markdown("No finding in this comparison.")
            else:
                record = delta.current
                witness = record.witness if isinstance(record, Finding) else record.possible_witness
                for i, candidate in enumerate(witness, start=1):
                    st.markdown(f"**Step {i}.** {md_escape(step_text(candidate))}: candidate {code(candidate.id)} is **{candidate.state}**")
                    st.markdown(prerequisite_table(candidate, comparison))
                if isinstance(record, Finding):
                    st.markdown("**Assumptions**\n" + "\n".join(f"- {md_escape(a)}" for a in record.assumptions))
        with tabs[1]:
            st.markdown(
                "\n".join(
                    [
                        "| Snapshot | Coverage | Rule A: direct S3 read | Rule B: role use via Lambda | Policy controls | Unmodelled mechanisms |",
                        "|---|---|---|---|---|---|",
                        coverage_row("Baseline", comparison.baseline),
                        coverage_row("Proposed", comparison.proposal),
                    ]
                )
            )
            issues = [(label, i) for label, a in (("Baseline", comparison.baseline), ("Proposed", comparison.proposal)) for i in a.coverage.issues]
            if issues:
                st.markdown(
                    "\n".join(
                        f"- :orange-badge[{label}] {md_escape(issue.message)}"
                        + (f" ({', '.join(code(p) for p in issue.pointers)})" if issue.pointers else "")
                        for label, issue in issues[:30]
                    )
                )
            st.markdown("\n".join(f"- {md_escape(n)}" for n in comparison.proposal.coverage.notes))
        with tabs[2]:
            if comparison.fact_changes:
                rows = ["| Fact | Statement | Baseline | Proposed | Pointer |", "|---|---|---|---|---|"]
                for change in comparison.fact_changes:
                    ptr = (change.proposal or change.baseline).pointer
                    rows.append(
                        f"| {code(change.fact_id)} | {md_escape(change.describe())} | {STATE_BADGE.get(change.before, md_escape(change.before))} | "
                        f"{STATE_BADGE.get(change.after, md_escape(change.after))} | {code(ptr)} |"
                    )
                st.markdown("\n".join(rows))
            else:
                st.markdown("No fact changed between the snapshots.")
            if comparison.config_changes:
                st.markdown("\n".join(f"- {md_escape(c.kind.replace('_', ' '))}: {md_escape(c.describe())}" for c in comparison.config_changes))
        with tabs[3]:
            lines = []
            for row in comparison.proposal.expected_access:
                check = row.check
                before = comparison.baseline.expected_result(check.id)
                states = [f"baseline {RESULT_BADGE[before.result] if before else 'not declared'}", f"proposed {RESULT_BADGE[row.result]}"]
                if sim:
                    after = sim.simulated.expected_result(check.id)
                    states.append(f"simulated {RESULT_BADGE[after.result] if after else 'n/a'}")
                lines.append(
                    f"- {code(check.principal)} {check.relationship.replace('_', ' ')} {code(check.target)}  \n"
                    f"  :small[{code(check.id)}] " + ", ".join(states)
                )
            st.markdown("\n".join(lines) or "The proposal declares no expected-access checks.")
            st.caption("Ordinary access a fix should preserve. It is never reported as a high-risk finding.")
        with tabs[4]:
            if delta is not None:
                record = delta.current
                witness = record.witness if isinstance(record, Finding) else record.possible_witness
                source = comparison.proposal if delta.proposal is not None else comparison.baseline
                st.graphviz_chart(witness_dot(source, witness, comparison.changed_fact_ids), width="content")
            st.caption("Rule B is one composite edge in the engine; the diagram above draws the Lambda function as a stop for readability.")
        with tabs[5]:
            explanations = tuple(r for (aid, _), r in st.session_state.explanations.items() if aid == comparison.analysis_id)
            report = build_report(comparison, result.fixes, sim, explanations)
            st.download_button(
                "Export Markdown report",
                data=report,
                file_name=f"attackgraph-report-{comparison.analysis_id}.md",
                mime="text/markdown",
                icon=":material/download:",
                on_click="ignore",
            )
            st.caption(
                f"Findings, evidence pointers, coverage, assumptions, the simulated fix and AI status. "
                f"Engine {ENGINE_VERSION}, model {MODEL_VERSION}, analysis {comparison.analysis_id}."
            )


def demo_section() -> None:
    st.html(
        web.section_head(
            "Watch one permission become an admin path",
            "The real engine on bundled synthetic snapshots. Switch scenario, or upload your own.",
            tag="Live demo",
            anchor="ag-demo",
            center=True,
        )
    )
    with st.container(horizontal=True, horizontal_alignment="center"):
        st.segmented_control(
            "Scenario",
            list(SCENARIO_LABELS),
            format_func=SCENARIO_LABELS.get,
            key="scenario",
            required=True,
            label_visibility="collapsed",
        )
    if st.session_state.scenario == UPLOAD:
        upload_panel()
    result = st.session_state.result
    if result is None:
        st.html(
            web.verdict(
                "info",
                "Add both snapshot files",
                "Upload a baseline and a proposed snapshot. Nothing is analysed until both are valid.",
            )
        )
        return
    if not result.ok:
        invalid_state(result)
        return
    verdict_block(result)
    stats_block(result)
    comparison = result.comparison
    delta = choose_finding(comparison)
    if delta is not None:
        story = build_story(comparison, delta)
        path_card(result, story)
        left, right = st.columns([2, 3], gap="medium")
        with left:
            change_card(comparison, story)
        with right:
            conditions_card(story)
        left, right = st.columns(2, gap="medium")
        with left:
            ai_card(result, delta, story)
        with right:
            fix_card(result, delta, story)
    evidence_section(result, delta)
    st.button("Start over", on_click=reset_app, help="Clears uploads, simulations and cached explanations.")


def main() -> None:
    st.set_page_config(page_title="AttackGraph AI", page_icon=":material/conversion_path:", layout="wide")
    init_state()
    sync_scenario()
    st.html(web.CSS)
    st.html(web.nav())
    st.html(web.hero(hero_preview()))
    st.html(web.statement())
    st.html(
        web.section_head(
            "From a config diff to a proven fix",
            "Each step can be checked against the input files.",
            tag="How it works",
            anchor="ag-how",
            center=True,
        )
    )
    st.html(web.how_it_works())
    demo_section()
    st.html('<div class="ag-section"></div>' + web.trust())
    st.html(web.footer())


main()
