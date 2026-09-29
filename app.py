"""AttackGraph AI workspace.

Run with: streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from attackgraph import ENGINE_VERSION, MODEL_VERSION
from attackgraph.analysis import IMPACT_TITLES, RULE_TITLES, Finding, PotentialFinding
from attackgraph.explain import (
    TIMEOUT_SECONDS,
    BedrockExplainer,
    ai_enabled,
    build_packet,
    configured_model,
    is_current,
    template_summary,
)
from attackgraph.pipeline import PipelineResult, run
from attackgraph.render import md_escape, md_segments, step_text, witness_dot
from attackgraph.report import build_report, verdict_text
from attackgraph.simulate import best_fix_for
from attackgraph.snapshot import KIND_TITLES, MAX_BYTES, POLICY_CONTROLS, UNMODELLED_MECHANISMS, LoadResult, load_snapshot

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
SCENARIOS = {
    "passrole": ("PassRole change: baseline vs proposed", "demo/baseline.json", "demo/proposed.json"),
    "repair": ("Repair check: proposed vs repaired", "demo/proposed.json", "demo/repaired.json"),
    "unknown": ("Incomplete coverage: unknown prerequisite", "demo/baseline.json", "examples/unknown-prerequisite.json"),
    "invalid": ("Validation errors: dangling reference and duplicate ID", "demo/baseline.json", "examples/invalid-references.json"),
}
STATUS = {
    "added": ("red", "Added"),
    "removed": ("green", "Removed"),
    "unchanged": ("gray", "Unchanged"),
    "inconclusive": ("orange", "Inconclusive"),
}
STATE_BADGE = {"true": ":blue-badge[true]", "false": ":gray-badge[false]", "unknown": ":orange-badge[unknown]"}
RESULT_BADGE = {"pass": ":blue-badge[pass]", "fail": ":red-badge[fail]", "inconclusive": ":orange-badge[inconclusive]"}
STATE_WORDS = {
    "reachable": "reachable",
    "unreachable": "not reachable",
    "inconclusive": "unresolved",
    "out_of_scope": "not a declared target",
}
STATUS_REASONS = {"invalid": "reply rejected", "refused": "model declined", "timeout": "timed out", "disabled": "turned off"}
CANDIDATE_WORDS = {"true": "established", "false": "blocked", "unknown": "unresolved"}
SNAPSHOT_TONES = {"baseline": ("gray", "BASELINE"), "proposal": ("blue", "PROPOSED"), "simulated": ("violet", "SIMULATED")}

CSS = """
<style>
[data-testid="stMarkdownContainer"] code { overflow-wrap: anywhere; white-space: pre-wrap; }
[data-testid="stMarkdownContainer"] table { width: 100%; }
[data-testid="stMarkdownContainer"] th { white-space: nowrap; vertical-align: bottom; }
[data-testid="stMarkdownContainer"] td { overflow-wrap: break-word; vertical-align: top; }
.block-container { padding-top: 2.2rem; max-width: 1480px; }
/* Heading anchor links add a tab stop per heading and serve no purpose in a workspace. */
[data-testid="stHeaderActionElements"] { display: none; }
</style>
"""


def code(value: str) -> str:
    return f"`{value}`"


def plural(count: int, noun: str) -> str:
    if count == 0:
        return f"no {noun}s"
    return f"{count} {noun}{'s' if count != 1 else ''}"


def init_state() -> None:
    for key, value in {
        "inputs": None,
        "result": None,
        "simulation": None,
        "explanations": {},
        "uploader_nonce": 0,
        "explainer": None,
    }.items():
        st.session_state.setdefault(key, value)


def clear_results() -> None:
    st.session_state.result = None
    st.session_state.simulation = None


def reset_app() -> None:
    nonce = st.session_state.get("uploader_nonce", 0) + 1
    st.session_state.clear()
    st.session_state.uploader_nonce = nonce


def load_demo() -> None:
    label, baseline, proposal = SCENARIOS[st.session_state.scenario]
    st.session_state.inputs = {
        "source": f"Bundled scenario: {label}",
        "baseline": (Path(baseline).name, (FIXTURES / baseline).read_bytes()),
        "proposal": (Path(proposal).name, (FIXTURES / proposal).read_bytes()),
    }
    clear_results()


def compare_inputs() -> None:
    inputs = st.session_state.inputs
    (baseline_name, baseline), (proposal_name, proposal) = inputs["baseline"], inputs["proposal"]
    st.session_state.result = run(baseline, baseline_name, proposal, proposal_name)
    st.session_state.simulation = None


def explainer() -> BedrockExplainer:
    model_id, region = configured_model()
    current = st.session_state.explainer
    if current is None or (current.model_id, current.region) != (model_id, region):
        current = st.session_state.explainer = BedrockExplainer(model_id, region)
    return current


def header() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("AttackGraph AI")
    st.markdown(
        "See how a proposed cloud configuration change affects access to sensitive resources before deployment.  \n"
        ":gray-badge[Synthetic configuration JSON] :gray-badge[Static analysis: nothing is deployed or executed] "
        ":blue-badge[Explanations: Amazon Bedrock]"
    )


def snapshot_card(role: str, loaded: LoadResult) -> None:
    color, title = SNAPSHOT_TONES[role]
    with st.container(border=True):
        st.markdown(f":{color}-badge[{title}] **{md_escape(loaded.source_name)}**")
        if loaded.ok:
            s = loaded.snapshot
            st.markdown(
                f"{md_escape(s.name)}  \n"
                f"Snapshot {code(s.snapshot_id)} · {len(s.nodes)} nodes · {len(s.facts)} facts · "
                f"{loaded.size_bytes:,} bytes · sha256 {code(loaded.sha256[:12])}  \n"
                ":gray-badge[synthetic: true] "
                f":gray-badge[model {s.model_version}]"
            )
        else:
            count = len(loaded.issues)
            st.error(
                f"**{count} validation error{'s' if count != 1 else ''}.** Neither file is analysed until both are valid.",
                icon=":material/error:",
            )
            st.markdown("\n".join(f"- {code(i.pointer or '(file)')}: {md_escape(i.message)}" for i in loaded.issues))


def snapshots_section() -> None:
    st.subheader("1. Snapshots")
    mode = st.segmented_control(
        "Input source",
        ["Bundled demo", "Upload JSON"],
        default="Bundled demo",
        required=True,
        key="mode",
    )
    if mode == "Bundled demo":
        left, right = st.columns([3, 1], vertical_alignment="bottom")
        left.selectbox("Scenario", list(SCENARIOS), format_func=lambda k: SCENARIOS[k][0], key="scenario")
        right.button("Load demo", on_click=load_demo, width="stretch")
    else:
        nonce = st.session_state.uploader_nonce
        left, right = st.columns(2)
        baseline = left.file_uploader(
            "Baseline snapshot (JSON)", type=["json"], key=f"upload-baseline-{nonce}", max_upload_size=2
        )
        proposal = right.file_uploader(
            "Proposed snapshot (JSON)", type=["json"], key=f"upload-proposal-{nonce}", max_upload_size=2
        )
        st.caption(f"Each file must follow the snapshot schema and be at most {MAX_BYTES // 1024:,} KiB.")
        if baseline and proposal:
            pair = {
                "source": "Uploaded files",
                "baseline": (baseline.name, baseline.getvalue()),
                "proposal": (proposal.name, proposal.getvalue()),
            }
            if pair != st.session_state.inputs:
                st.session_state.inputs = pair
                clear_results()
        elif baseline or proposal:
            st.info("Add the second file to compare.", icon=":material/upload_file:")

    with st.expander("Snapshot format and rules"):
        schema_help()

    inputs = st.session_state.inputs
    if inputs is None:
        st.info(
            "Nothing loaded yet. Load the bundled demo or upload a baseline and a proposed snapshot, then compare them.",
            icon=":material/info:",
        )
        return
    st.caption(f"Active input: {md_escape(inputs['source'])}")
    loaded = {role: load_snapshot(data, name) for role, (name, data) in ((r, inputs[r]) for r in ("baseline", "proposal"))}
    left, right = st.columns(2)
    with left:
        snapshot_card("baseline", loaded["baseline"])
    with right:
        snapshot_card("proposal", loaded["proposal"])
    actions = st.container(horizontal=True)
    actions.button("Compare changes", type="primary", on_click=compare_inputs, icon=":material/compare_arrows:")
    actions.button("Reset app", on_click=reset_app, help="Clears loaded files, results, simulations and cached explanations.")


def schema_help() -> None:
    st.markdown(
        "Snapshots are hand-authored **synthetic** JSON files, not Terraform or raw IAM policies. "
        "Labels are display text only and never grant privilege. The full schema is "
        f"{code('attackgraph/snapshot.schema.json')}."
    )
    st.code(
        """{
  "schema_version": "1.0",
  "snapshot_id": "demo-proposed",
  "synthetic": true,
  "model_version": "attackgraph-rules-v1",
  "coverage": {
    "policy_controls": {"permissions_boundaries": "resolved", "service_control_policies": "resolved",
                        "resource_policies": "resolved", "conditions": "resolved", "explicit_denies": "resolved"},
    "unmodelled_mechanisms": []
  },
  "nodes": [{"id": "p-ci-deployer", "kind": "principal", "label": "CI deploy user", "account_id": "syn-app-prod"}],
  "facts": [{"id": "f-ci-pass-deploy-admin", "predicate": "iam_pass_role_to_lambda",
             "subject": "p-ci-deployer", "object": "r-deploy-admin", "state": "true"}],
  "entry_principals": ["p-ci-deployer"],
  "protected_targets": [{"node": "r-deploy-admin", "classification": "privileged_role"}],
  "expected_access": [{"id": "ea-ci-reads-build-artifacts", "principal": "p-ci-deployer",
                       "target": "o-build-artifacts", "relationship": "object_read"}]
}""",
        language="json",
    )
    st.markdown(
        f"- **{RULE_TITLES['s3_direct_read']}.** The subject has a declared effective `s3:GetObject` fact for that exact object.\n"
        f"- **{RULE_TITLES['lambda_pass_role']}.** All must be true for the same subject, role and workload: pass the role to "
        "Lambda, create and invoke the workload, control its code (scenario assumption), the role trusts Lambda, one "
        "synthetic account, and policy controls declared resolved. `iam:PassRole` alone never establishes access.\n"
        "- Fact states are `true`, `false` or `unknown`. A prerequisite with no declared fact is `unknown`, and any "
        "unresolved candidate makes coverage incomplete instead of safe."
    )


def coverage_row(label: str, analysis) -> str:
    cov = analysis.coverage
    rules = [
        f"{c['true']} established · {c['false']} blocked · {c['unknown']} unresolved"
        for c in (cov.candidate_counts["s3_direct_read"], cov.candidate_counts["lambda_pass_role"])
    ]
    unresolved = [POLICY_CONTROLS[k].lower() for k, v in analysis.snapshot.policy_controls.items() if v != "resolved"]
    policy = "all 5 resolved" if not unresolved else ":orange-badge[unresolved] " + ", ".join(unresolved)
    mechanisms = ", ".join(UNMODELLED_MECHANISMS[m] for m in analysis.snapshot.unmodelled_mechanisms) or "none"
    badge = ":blue-badge[complete]" if cov.complete else ":orange-badge[incomplete]"
    return f"| {label} | {badge} | {rules[0]} | {rules[1]} | {policy} | {md_escape(mechanisms)} |"


def results_header(result: PipelineResult) -> None:
    comparison = result.comparison
    st.subheader("2. Result")
    verdict = comparison.verdict
    message = verdict_text(comparison)
    if verdict == "new_high_risk":
        st.error(f"**{message}**", icon=":material/warning:")
    elif verdict == "no_new_high_risk":
        st.success(f"**{message}** Complete for the declared synthetic model, not for an AWS account.", icon=":material/check_circle:")
    else:
        st.warning(f"**{message}**", icon=":material/help:")

    simulation = active_simulation(result)
    columns = st.columns(4)
    columns[0].metric("Baseline high-risk", comparison.baseline.high_risk_count, border=True, height="stretch")
    columns[1].metric(
        "Proposed high-risk",
        comparison.proposal.high_risk_count,
        delta=comparison.proposal.high_risk_count - comparison.baseline.high_risk_count or None,
        delta_color="inverse",
        border=True,
        height="stretch",
    )
    if simulation:
        columns[2].metric(
            "Simulated fix high-risk",
            simulation.simulated.high_risk_count,
            delta=simulation.simulated.high_risk_count - comparison.proposal.high_risk_count or None,
            delta_color="inverse",
            border=True,
            height="stretch",
        )
    else:
        columns[2].metric("Simulated fix high-risk", "-", help="Run Simulate fix on a finding.", border=True, height="stretch")
    columns[3].metric("Coverage", "Complete" if comparison.complete else "Incomplete", border=True, height="stretch")

    st.markdown("**Model coverage**")
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
    with st.expander(f"Coverage details ({len(issues)} unresolved item{'s' if len(issues) != 1 else ''})", expanded=bool(issues)):
        if issues:
            lines = [
                f"- :orange-badge[{label}] {md_escape(issue.message)}"
                + (f" ({', '.join(code(p) for p in issue.pointers)})" if issue.pointers else "")
                for label, issue in issues[:30]
            ]
            if len(issues) > 30:
                lines.append(f"- {len(issues) - 30} more unresolved items are listed in the exported report.")
            st.markdown("\n".join(lines))
        else:
            st.markdown("Every evaluated candidate resolved to true or false, and no unresolved control or unmodelled mechanism is declared.")
        st.markdown("\n".join(f"- {md_escape(n)}" for n in comparison.proposal.coverage.notes))

    st.markdown("**What changed**")
    if comparison.fact_changes:
        rows = ["| Fact | Statement | Baseline | Proposed | Pointer |", "|---|---|---|---|---|"]
        for change in comparison.fact_changes:
            flag = " :red-badge[newly enabled grant]" if change.newly_enabled else ""
            ptr = (change.proposal or change.baseline).pointer
            rows.append(
                f"| {code(change.fact_id)} | {md_escape(change.describe())}{flag} | {state_cell(change.before)} | "
                f"{state_cell(change.after)} | {code(ptr)} |"
            )
        st.markdown("\n".join(rows))
    else:
        st.markdown("No fact changed between the snapshots.")
    if comparison.config_changes:
        st.markdown("\n".join(f"- {md_escape(c.kind.replace('_', ' '))}: {md_escape(c.describe())}" for c in comparison.config_changes))


def state_cell(state: str) -> str:
    return STATE_BADGE.get(state, md_escape(state))


def active_simulation(result: PipelineResult):
    sim = st.session_state.simulation
    if not sim or sim["analysis_id"] != result.comparison.analysis_id:
        return None
    return next((f for f in result.fixes if f.id == sim["fix_id"]), None)


def finding_label(delta) -> str:
    color, word = STATUS[delta.status]
    extras = []
    if delta.provisional:
        extras.append(":orange[provisional]")
    if delta.evidence_changed:
        extras.append(":blue[evidence changed]")
    target_kind = "privileged role" if delta.impact == "privileged_role_use" else "sensitive object"
    return (
        f":{color}-badge[{word}] :red-badge[{delta.severity}] {code(delta.entry)} → {target_kind} {code(delta.target)}"
        + (" " + " ".join(extras) if extras else "")
    )


def findings_column(result: PipelineResult):
    comparison = result.comparison
    st.markdown("#### Findings")
    deltas = comparison.deltas
    if not deltas:
        if comparison.complete:
            st.success("No modelled high-risk access in either snapshot.", icon=":material/check_circle:")
        else:
            st.warning(
                "No established or unresolved route to a protected target, but coverage is incomplete, so this is not a safe verdict.",
                icon=":material/help:",
            )
        return None
    counts = ", ".join(f"{comparison.count(s)} {STATUS[s][1].lower()}" for s in STATUS if comparison.count(s))
    st.caption(f"{len(deltas)} finding{'s' if len(deltas) != 1 else ''}: {counts}. Severity High = reachable protected target (demo rubric).")
    selected = st.radio(
        "Select a finding",
        [d.id for d in deltas],
        format_func=lambda key: finding_label(comparison.delta(key)),
        captions=[
            f"Baseline {STATE_WORDS[d.baseline_state]} → proposed {STATE_WORDS[d.proposal_state]} · {IMPACT_TITLES[d.impact]}"
            for d in deltas
        ],
        key=f"finding-{comparison.analysis_id}",
        label_visibility="collapsed",
    )
    return comparison.delta(selected)


def expected_access_block(result: PipelineResult) -> None:
    comparison = result.comparison
    simulation = active_simulation(result)
    st.markdown("#### Expected access (informational)")
    checks = comparison.proposal.expected_access
    if not checks:
        st.caption("The proposal declares no expected-access checks.")
        return
    lines = []
    for result_row in checks:
        check = result_row.check
        before = comparison.baseline.expected_result(check.id)
        states = [
            f"baseline {RESULT_BADGE[before.result] if before else 'not declared'}",
            f"proposed {RESULT_BADGE[result_row.result]}",
        ]
        if simulation:
            after = simulation.simulated.expected_result(check.id)
            states.append(f"simulated {RESULT_BADGE[after.result] if after else 'n/a'}")
        lines.append(
            f"- {code(check.principal)} {check.relationship.replace('_', ' ')} {code(check.target)}  \n"
            f"  :small[{code(check.id)}] · " + " · ".join(states)
        )
    st.markdown("\n".join(lines))
    st.caption("Ordinary access a fix should preserve. It is never reported as a high-risk finding.")


def prerequisite_table(candidate, comparison) -> str:
    rows = ["| State | Prerequisite | Evidence | JSON pointer |", "|---|---|---|---|"]
    for p in candidate.prerequisites:
        evidence = code(p.fact_id) if p.fact_id else ("not declared" if p.origin == "missing" else "derived")
        change = comparison.fact_change(p.fact_id) if p.fact_id else None
        if change is not None:
            evidence += f" :red-badge[changed {change.before} → {change.after}]"
        if p.assumption:
            evidence += " :violet-badge[scenario assumption]"
        note = f" ({md_escape(p.note)})" if p.note and p.state != "true" else ""
        pointers = ", ".join(code(ptr) for ptr in p.pointers) or "-"
        rows.append(f"| {state_cell(p.state)} | {md_escape(p.text)}{note} | {evidence} | {pointers} |")
    return "\n".join(rows)


def witness_block(comparison, analysis, witness, heading: str) -> None:
    st.markdown(f"**{heading}**")
    for step, candidate in enumerate(witness, start=1):
        with st.container(border=True):
            state = {"true": ":blue-badge[established]", "unknown": ":orange-badge[unresolved]"}.get(candidate.state, ":gray-badge[blocked]")
            st.markdown(f"**Step {step}.** {md_escape(step_text(candidate))} {state}  \n:small[Candidate {code(candidate.id)}]")
            st.markdown(prerequisite_table(candidate, comparison))
    with st.expander("Graph witness (same edges as the text path)", expanded=True):
        st.graphviz_chart(witness_dot(analysis, witness, comparison.changed_fact_ids), width="content")


def baseline_contrast(comparison, delta, witness) -> None:
    """For an added finding, show how the baseline evaluated the same route."""
    if delta.status != "added":
        return
    lines = []
    for candidate in witness:
        before = comparison.baseline.candidates.get(candidate.id)
        if before is None:
            lines.append(f"- {code(candidate.id)}: not evaluated in the baseline because {code(candidate.subject)} was not reachable there.")
            continue
        blockers = [p for p in before.prerequisites if p.state != "true"]
        reasons = ", ".join(
            f"{code(p.fact_id) if p.fact_id else md_escape(p.key)} was {p.state}" for p in blockers
        ) or "all prerequisites were true"
        lines.append(f"- {code(candidate.id)} was **{CANDIDATE_WORDS[before.state]}** in the baseline: {reasons}.")
    if lines:
        st.markdown("**Same route in the baseline**  \n" + "\n".join(lines))


def detail_column(result: PipelineResult, delta) -> None:
    comparison = result.comparison
    record = delta.current
    color, word = STATUS[delta.status]
    st.markdown(f"#### :{color}-badge[{word}] :red-badge[{delta.severity}] {md_escape(record.describe())}")
    st.markdown(
        f"Finding {code(delta.id)}  \n"
        f"Baseline: **{STATE_WORDS[delta.baseline_state]}** · Proposed: **{STATE_WORDS[delta.proposal_state]}** · "
        f"target classification {code(delta.classification)}"
    )
    if delta.provisional:
        st.warning("Provisional: at least one snapshot has incomplete coverage, so this delta is not confirmed.", icon=":material/help:")
    if delta.evidence_changed:
        st.info("The finding exists in both snapshots, but its supporting evidence changed.", icon=":material/sync_alt:")

    source = comparison.proposal if delta.proposal is not None else comparison.baseline
    where = "proposed" if delta.proposal is not None else "baseline"
    if isinstance(record, Finding):
        witness_block(comparison, source, record.witness, f"Evidence path in the {where} snapshot")
        baseline_contrast(comparison, delta, record.witness)
        st.markdown("**Assumptions**  \n" + "\n".join(f"- {md_escape(a)}" for a in record.assumptions))
    elif isinstance(record, PotentialFinding):
        st.warning(
            "Unresolved: this protected target is reachable only through candidates with unknown prerequisites. "
            "It is not a finding, and it is not safe.",
            icon=":material/help:",
        )
        witness_block(comparison, source, record.possible_witness, f"Possible route in the {where} snapshot (not established)")

    explanation_block(result, delta)
    simulation_block(result, delta)


def explanation_block(result: PipelineResult, delta) -> None:
    comparison = result.comparison
    st.markdown("---")
    st.markdown("#### Why this matters")
    model_id, region = configured_model()
    key = (comparison.analysis_id, delta.id)
    stored = st.session_state.explanations.get(key)
    if stored is not None and not is_current(stored, comparison.analysis_id):
        stored = None

    enabled = ai_enabled()
    help_text = f"Sends an evidence packet of aliases only (no labels or IDs) to {model_id} in {region}. Timeout {TIMEOUT_SECONDS} s."
    if st.button(
        "Explain with Amazon Bedrock",
        icon=":material/auto_awesome:",
        disabled=not enabled,
        help=help_text if enabled else "AI explanations are turned off (ATTACKGRAPH_AI=off).",
        key=f"explain-{delta.id}",
    ):
        packet = build_packet(comparison, delta, result.fixes)
        with st.spinner(f"Asking Amazon Bedrock ({model_id})..."):
            outcome = explainer().explain(packet)
        if is_current(outcome, comparison.analysis_id):
            st.session_state.explanations[key] = outcome
            stored = outcome

    template = template_summary(comparison, delta, result.fixes)
    if stored is None:
        st.markdown(":gray-badge[Template summary: deterministic, not AI-generated]")
        st.markdown(template)
        st.caption("Select Explain for an AI explanation. The evidence above stays authoritative.")
        return
    if stored.ok:
        meta = [f"model {code(stored.model_id)}", f"region {code(stored.region)}", f"at {stored.created_at}"]
        if stored.request_id:
            meta.append(f"request {code(stored.request_id)}")
        if stored.input_tokens is not None:
            meta.append(f"{stored.input_tokens:,} in / {stored.output_tokens:,} out tokens")
        if stored.latency_ms is not None:
            meta.append(f"{stored.latency_ms / 1000:.1f} s")
        cached = " :gray-badge[cached: no new model call]" if stored.cached else ""
        with st.container(border=True):
            st.markdown(f":violet-badge[AI explanation: Amazon Bedrock]{cached}  \n:small[{' · '.join(meta)}]")
            st.markdown(md_segments(stored.summary))
            cited = ", ".join(code(e) if " " not in e else md_escape(e) for e in stored.evidence_ids)
            st.markdown(
                f"**Evidence cited:** {cited}  \n**Fix cited:** {code(stored.cited_fix) if stored.cited_fix else 'none'}  \n"
                f"**Limitations:** {md_segments(stored.limitations)}"
            )
        st.caption("Generated text. Identifier checks passed, but check the prose against the evidence above.")
        with st.expander("Deterministic template summary"):
            st.markdown(template)
    else:
        reason = "" if stored.status == "unavailable" else f" ({STATUS_REASONS.get(stored.status, stored.status)})"
        st.warning(f"**AI explanation unavailable**{reason}. {md_escape(stored.error)}", icon=":material/cloud_off:")
        st.markdown(":gray-badge[Template summary: deterministic, not AI-generated]")
        st.markdown(template)


def start_simulation(analysis_id: str, fix_id: str) -> None:
    st.session_state.simulation = {"analysis_id": analysis_id, "fix_id": fix_id}


def stop_simulation() -> None:
    st.session_state.simulation = None


def simulation_block(result: PipelineResult, delta) -> None:
    comparison = result.comparison
    st.markdown("---")
    st.markdown("#### Simulate fix")
    if delta.proposal is None:
        st.info("This finding is not present in the proposal, so there is nothing to fix.", icon=":material/info:")
        return
    if delta.status == "inconclusive":
        st.warning("No verified fix: this finding is unresolved. Declare the unknown facts first.", icon=":material/help:")
        return
    fixes = result.fixes
    if not fixes:
        reason = "the access already existed in the baseline" if delta.status == "unchanged" else "no newly enabled grant is on its route"
        st.info(f"No single-permission fix to test: {reason}.", icon=":material/info:")
        return
    best = best_fix_for(fixes, delta.id)
    if best is None:
        st.warning(
            "No effective single-permission fix: revoking any one newly enabled grant leaves another route to this target.",
            icon=":material/warning:",
        )
    options = [f.id for f in fixes]
    default = options.index(best.id) if best else 0
    choice = st.radio(
        "Engine-tested candidates (single revocations of newly enabled grants)",
        options,
        index=default,
        format_func=lambda fid: fix_label(next(f for f in fixes if f.id == fid), delta.id),
        key=f"fix-{comparison.analysis_id}-{delta.id}",
    )
    if result.untested_fixes:
        st.caption(f"{result.untested_fixes} further eligible grants were not simulated (limit reached).")
    fix = next(f for f in fixes if f.id == choice)
    active = active_simulation(result)
    buttons = st.container(horizontal=True)
    buttons.button(
        "Simulate fix",
        type="primary",
        icon=":material/science:",
        on_click=start_simulation,
        args=(comparison.analysis_id, fix.id),
        key=f"simulate-{delta.id}",
    )
    if active is not None:
        buttons.button("Reset simulation", on_click=stop_simulation, key=f"reset-sim-{delta.id}")
        simulation_panel(result, active, delta)


def fix_label(fix, finding_id: str) -> str:
    if fix.verified_for(finding_id):
        verdict = ":blue-badge[Verified in this model]"
    elif fix.removes(finding_id):
        verdict = ":orange-badge[removes it; coverage incomplete after]"
    else:
        verdict = ":gray-badge[finding remains: another route]"
    kept = sum(1 for r in fix.expected_after if r.result == "pass")
    return (
        f"Revoke {code(fix.fact_id)} {verdict}  \n"
        f":small[{md_escape(fix.proposal_fact.describe())} · {plural(len(fix.remaining), 'high-risk finding')} left · "
        f"expected access {kept}/{len(fix.expected_after)} pass]"
    )


def simulation_panel(result: PipelineResult, fix, delta) -> None:
    comparison = result.comparison
    color, title = SNAPSHOT_TONES["simulated"]
    with st.container(border=True):
        st.markdown(
            f":{color}-badge[{title}] In-memory copy of the proposal with {code(fix.fact_id)} set from `true` to `false` "
            f"(record kept at {code(fix.proposal_fact.pointer)}). The uploaded files are unchanged."
        )
        columns = st.columns(2)
        columns[0].metric("Proposed high-risk", comparison.proposal.high_risk_count)
        columns[1].metric(
            "After simulated fix",
            fix.simulated.high_risk_count,
            delta=fix.simulated.high_risk_count - comparison.proposal.high_risk_count or None,
            delta_color="inverse",
        )
        verified = fix.verified_for(delta.id)
        if verified:
            st.success(f"**Verified in this model:** revoking {code(fix.fact_id)} removes this finding and coverage stays complete.", icon=":material/verified:")
        elif fix.removes(delta.id):
            st.warning("The finding disappears, but coverage is incomplete after the change, so the fix is not verified.", icon=":material/help:")
        else:
            st.warning("The finding remains through another route.", icon=":material/warning:")
        lines = [
            f"- Removed: {', '.join(code(k) for k in fix.removed) or 'none'}",
            f"- Remaining: {', '.join(code(k) for k in fix.remaining) or 'none'}",
        ]
        if fix.now_inconclusive:
            lines.append(f"- Unresolved after the change: {', '.join(code(k) for k in fix.now_inconclusive)}")
        changes = fix.expected_changes
        lines.append(
            "- Expected access: "
            + ("; ".join(f"{code(c)} {b} → {a}" for c, b, a in changes) if changes else "every check keeps its proposed result")
        )
        lines.append(f"- Coverage after the change: {'complete' if fix.coverage_complete else 'incomplete'}")
        st.markdown("\n".join(lines))
        remaining = fix.simulated.findings.get(delta.id)
        if remaining is not None:
            st.markdown("**Remaining route**  \n" + "\n".join(f"{i}. {md_escape(step_text(c))}" for i, c in enumerate(remaining.witness, 1)))


def export_section(result: PipelineResult) -> None:
    comparison = result.comparison
    st.subheader("3. Export")
    explanations = tuple(
        r for (analysis_id, _), r in st.session_state.explanations.items() if analysis_id == comparison.analysis_id
    )
    report = build_report(comparison, result.fixes, active_simulation(result), explanations)
    st.download_button(
        "Export Markdown report",
        data=report,
        file_name=f"attackgraph-report-{comparison.analysis_id}.md",
        mime="text/markdown",
        icon=":material/download:",
        on_click="ignore",
    )
    st.caption(
        f"Includes findings, evidence pointers, coverage, assumptions, the simulated fix and AI status. "
        f"Engine {ENGINE_VERSION}, model {MODEL_VERSION}, analysis {comparison.analysis_id}."
    )


def main() -> None:
    st.set_page_config(page_title="AttackGraph AI", page_icon=":material/shield:", layout="wide")
    init_state()
    header()
    snapshots_section()
    result = st.session_state.result
    if result is None:
        return
    if not result.ok:
        st.error("Analysis not run: fix the validation errors above. Neither file was analysed.", icon=":material/error:")
        return
    st.divider()
    results_header(result)
    st.divider()
    left, right = st.columns([2, 3], gap="large")
    with left:
        delta = findings_column(result)
        expected_access_block(result)
    with right:
        if delta is None:
            st.markdown("#### Evidence")
            st.caption("Select a finding to inspect its evidence, explanation and fix simulation.")
        else:
            detail_column(result, delta)
    st.divider()
    export_section(result)


main()
