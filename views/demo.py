"""Live demo page: the real engine on bundled or uploaded snapshots, with live Bedrock explanations.

Served at /demo by app.py. Deep link a scenario with ?scenario=passrole|repair|unknown|invalid|upload.
"""

from __future__ import annotations

import hashlib
import json

import streamlit as st

from attackgraph import ENGINE_VERSION, MODEL_VERSION, landing, page, web
from attackgraph.analysis import RULE_TITLES, Finding
from attackgraph.explain import (
    PROMPT_VERSION,
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
from attackgraph.scenarios import SCENARIO_LABELS, UPLOAD, run_scenario
from attackgraph.simulate import best_fix_for
from attackgraph.snapshot import MAX_BYTES, POLICY_CONTROLS, UNMODELLED_MECHANISMS
from attackgraph.story import build_story, summary

STATE_BADGE = {"true": ":blue-badge[true]", "false": ":gray-badge[false]", "unknown": ":orange-badge[unknown]"}
RESULT_BADGE = {"pass": ":green-badge[pass]", "fail": ":red-badge[fail]", "inconclusive": ":orange-badge[inconclusive]"}
REASONS = {"invalid": "reply rejected", "refused": "model declined", "timeout": "timed out", "disabled": "turned off"}


def code(value: str) -> str:
    return f"`{value}`"


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
        st.session_state.result = run_scenario(scenario)
        st.session_state.loaded = ("scenario", scenario)
        st.session_state.simulation = None


def reset_app() -> None:
    nonce = st.session_state.get("uploader_nonce", 0) + 1
    st.session_state.clear()
    st.session_state.uploader_nonce = nonce


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


def choose_finding(comparison):
    deltas = comparison.deltas
    if not deltas:
        return None
    if len(deltas) == 1:
        return deltas[0]
    key = st.selectbox(
        "Finding to walk through",
        [d.id for d in deltas],
        format_func=lambda k: f"{page.STATUS_WORDS[comparison.delta(k).status]}: {build_story(comparison, comparison.delta(k)).headline}",
        key=f"finding-{comparison.analysis_id}",
    )
    return comparison.delta(key)


def ai_card(result: PipelineResult, delta, story) -> None:
    comparison = result.comparison
    model_id, region = configured_model()
    key = (comparison.analysis_id, delta.id)
    stored = st.session_state.explanations.get(key)
    if stored is not None and not is_current(stored, comparison.analysis_id):
        stored = None
    packet = build_packet(comparison, delta, result.fixes)
    enabled = ai_enabled()
    fix = next((f for f in result.fixes if f.removes(delta.id)), None)
    plain = web.summary(summary(story, fix))
    with st.container(key="agcard-ai"):
        st.html(page.ai_intro(model_id))
        left, right = st.columns([3, 2], gap="large")
        with left:
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
            if stored is None:
                st.markdown(":gray-badge[Deterministic summary, not AI-generated]")
                st.html(plain)
            elif stored.ok:
                cached = " :gray-badge[cached: no new call]" if stored.cached else ""
                st.markdown(f":green-badge[AI explanation]{cached}")
                st.markdown(md_segments(stored.summary))
                st.markdown(f":small[**Limitations:** {md_segments(stored.limitations)}]")
            else:
                reason = "" if stored.status == "unavailable" else f" ({REASONS.get(stored.status, stored.status)})"
                st.warning(f"**AI explanation unavailable**{reason}. {md_escape(stored.error)}", icon=":material/cloud_off:")
                st.markdown(":gray-badge[Deterministic summary, not AI-generated]")
                st.html(plain)
        with right:
            rows = [("Model", model_id), ("Region", region), ("Prompt", PROMPT_VERSION)]
            if stored is not None and stored.ok:
                if stored.request_id:
                    rows.append(("Request", stored.request_id))
                if stored.input_tokens is not None:
                    rows.append(("Tokens", f"{stored.input_tokens:,} in, {stored.output_tokens:,} out"))
                if stored.latency_ms is not None:
                    rows.append(("Latency", f"{stored.latency_ms / 1000:.1f} s"))
            st.html(web.meta_list(rows))
            if stored is not None and stored.ok:
                with st.expander("Deterministic summary for comparison"):
                    st.html(plain)
            with st.expander("What the model sees"):
                st.caption("The complete evidence packet sent to Bedrock. Every name is a placeholder; the page maps them back.")
                st.code(json.dumps(packet.payload, indent=1), language="json")


def fix_card(result: PipelineResult, delta, story) -> None:
    comparison = result.comparison
    sim = active_simulation(result)
    with st.container(key="agcard-fix"):
        st.html(web.card_head("healing", "The fix"))
        blocker = page.fix_blocker(result, delta)
        if blocker:
            st.html(f'<p class="ag-note">{web.esc(blocker)}</p>')
            return
        best = best_fix_for(result.fixes, delta.id)
        options = [f.id for f in result.fixes]
        chosen = best or result.fixes[0]
        expected = page.expected_block(comparison, sim)
        left, right = st.columns(2, gap="large") if expected else (st.container(), None)
        with left:
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
            st.html(page.fix_intro(chosen, best, story))
            buttons = st.container(horizontal=True)
            buttons.button(
                "Simulate the fix",
                type="primary",
                icon=":material/science:",
                on_click=start_simulation,
                args=(comparison.analysis_id, chosen.id),
                key=f"simulate-{delta.id}",
            )
            if sim is not None:
                buttons.button("Reset simulation", on_click=stop_simulation, key=f"reset-sim-{delta.id}")
                st.html(page.fix_result(comparison, delta, sim))
        if right is not None:
            with right:
                st.html(expected)


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
        st.html(page.invalid(result))
        return
    sim = active_simulation(result)
    st.html(page.verdict(result) + page.stats(result, sim))
    comparison = result.comparison
    delta = choose_finding(comparison)
    if delta is not None:
        story = build_story(comparison, delta)
        for key, card in (
            ("path", page.path_card(story, sim)),
            ("change", page.change_card(comparison, story)),
            ("conds", page.conditions_card(story)),
        ):
            with st.container(key=f"agcard-{key}"):
                st.html(card)
        ai_card(result, delta, story)
        fix_card(result, delta, story)
    evidence_section(result, delta)
    st.button("Start over", on_click=reset_app, help="Clears uploads, simulations and cached explanations.")


init_state()
sync_scenario()
st.html(web.nav(web.DEMO) + landing.demo_header())
demo_section()
st.html(landing.footer(hosted=False))
