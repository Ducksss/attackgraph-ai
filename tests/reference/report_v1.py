# FROZEN ORACLE. A verbatim copy of attackgraph/report.py at commit a222929, the engine
# before the Rule B performance work. tests/test_differential.py runs it beside the
# live engine and requires identical results. Do not edit, reformat or fix it: only
# the imports differ from the original, so that the copies use each other.

"""Markdown export built from the same objects the UI displays."""

from __future__ import annotations

from datetime import datetime, timezone

from attackgraph import ENGINE_VERSION, MODEL_VERSION, SCHEMA_VERSION
from .analysis_v1 import IMPACT_TITLES, RULE_TITLES, Finding, PotentialFinding, SnapshotAnalysis
from .compare_v1 import Comparison, FindingDelta
from attackgraph.explain import ExplanationResult, template_summary
from attackgraph.render import fenced, md_escape, plain_segments, step_text
from .simulate_v1 import FixCandidate
from attackgraph.snapshot import KIND_TITLES, Snapshot

LIMITATIONS = (
    "Input is hand-authored synthetic configuration JSON. Terraform, CloudFormation and raw IAM policies are not parsed.",
    "Only two rule families are modelled: direct S3 object reads (Rule A) and role use through a Lambda workload (Rule B).",
    "Permissions boundaries, SCPs, resource policies, conditions and explicit denies are not evaluated; the fixture declares whether their effect is already reflected in its facts.",
    "Complete coverage means complete for the declared synthetic model, not for an AWS account.",
    "Fix candidates are single revocations of newly enabled grants. They are not a minimum cut and do not prove that real business workflows keep working.",
    "The AI explanation is generated text. Identifier checks do not prove its prose is true; the deterministic evidence is authoritative.",
)

MAX_LISTED_ISSUES = 25
STATUS_WORDS = {"added": "Added", "removed": "Removed", "unchanged": "Unchanged", "inconclusive": "Inconclusive"}


def _code(value: str) -> str:
    return f"`{value}`"


def _snapshot_row(role: str, s: Snapshot) -> str:
    return (
        f"| {role} | {_code(s.snapshot_id)} · {md_escape(s.name)} · file {md_escape(s.source_name)} · "
        f"sha256 {_code(s.sha256[:16])} · synthetic: {str(s.synthetic).lower()} |"
    )


def verdict_text(comparison: Comparison) -> str:
    added = comparison.count("added")
    if comparison.verdict == "incomplete":
        return "Analysis incomplete. Deltas are provisional and no result is a safe verdict."
    if comparison.verdict == "new_high_risk":
        return f"{added} new high-risk finding{'s' if added != 1 else ''} in the proposal."
    return "No new modelled high-risk access."


def _coverage_lines(label: str, analysis: SnapshotAnalysis) -> list[str]:
    cov = analysis.coverage
    counts = "; ".join(
        f"{RULE_TITLES[rule]}: {c['true']} established, {c['false']} blocked, {c['unknown']} unresolved"
        for rule, c in cov.candidate_counts.items()
    )
    lines = [f"- **{label}: {'complete' if cov.complete else 'incomplete'}.** {counts}."]
    for issue in cov.issues[:MAX_LISTED_ISSUES]:
        where = ", ".join(_code(p) for p in issue.pointers)
        lines.append(f"  - {md_escape(issue.message)}" + (f" ({where})" if where else ""))
    hidden = len(cov.issues) - MAX_LISTED_ISSUES
    if hidden > 0:
        lines.append(f"  - {hidden} more unresolved item{'s' if hidden != 1 else ''} not listed.")
    return lines


def _witness_lines(analysis: SnapshotAnalysis, witness, changed: frozenset[str]) -> list[str]:
    lines = []
    for step, candidate in enumerate(witness, start=1):
        lines.append(f"{step}. {md_escape(step_text(candidate))}: candidate {_code(candidate.id)} is **{candidate.state}**")
        lines.append("")
        lines.append("   | Prerequisite | State | Evidence | JSON pointer |")
        lines.append("   |---|---|---|---|")
        for p in candidate.prerequisites:
            evidence = _code(p.fact_id) if p.fact_id else ("not declared" if p.origin == "missing" else "derived")
            if p.fact_id and p.fact_id in changed:
                evidence += " **CHANGED**"
            if p.assumption:
                evidence += " (scenario assumption)"
            pointers = ", ".join(_code(ptr) for ptr in p.pointers) or "-"
            note = f" ({md_escape(p.note)})" if p.note and p.state != "true" else ""
            lines.append(f"   | {md_escape(p.text)}{note} | {p.state} | {evidence} | {pointers} |")
        lines.append("")
    return lines


def _finding_section(comparison: Comparison, delta: FindingDelta) -> list[str]:
    record = delta.current
    source = comparison.proposal if delta.proposal is not None else comparison.baseline
    which = "proposal" if delta.proposal is not None else "baseline"
    status = STATUS_WORDS[delta.status] + (" (provisional)" if delta.provisional else "")
    lines = [
        f"### {status} · {delta.severity} · {md_escape(record.describe())}",
        "",
        f"- Finding ID: {_code(delta.id)}",
        f"- Impact: {IMPACT_TITLES[delta.impact]}; target classification {_code(delta.classification)}",
        f"- Baseline: {delta.baseline_state}; proposal: {delta.proposal_state}"
        + ("; **evidence changed**" if delta.evidence_changed else ""),
        "",
    ]
    if isinstance(record, Finding):
        lines.append(f"Witness in the {which} snapshot:")
        lines.append("")
        lines += _witness_lines(source, record.witness, comparison.changed_fact_ids)
        lines.append("Assumptions:")
        lines += [f"- {md_escape(a)}" for a in record.assumptions]
        lines.append("")
    elif isinstance(record, PotentialFinding):
        lines.append(f"Possible route in the {which} snapshot (not established):")
        lines.append("")
        lines += _witness_lines(source, record.possible_witness, comparison.changed_fact_ids)
    return lines


def _explanation_lines(result: ExplanationResult, comparison: Comparison, fixes) -> list[str]:
    delta = comparison.delta(result.finding_id)
    title = md_escape(delta.describe()) if delta else _code(result.finding_id)
    meta = [
        f"status **{result.status}**" + (" (cached)" if result.cached else ""),
        f"model {_code(result.model_id)}",
        f"region {_code(result.region)}",
        f"prompt {_code(result.prompt_version)}",
        f"at {result.created_at}",
    ]
    if result.request_id:
        meta.append(f"request ID {_code(result.request_id)}")
    if result.input_tokens is not None:
        meta.append(f"tokens {result.input_tokens} in / {result.output_tokens} out")
    if result.latency_ms is not None:
        meta.append(f"latency {result.latency_ms} ms")
    lines = [f"### {title}", "", "- " + " · ".join(meta)]
    if result.ok:
        lines += ["", "Generated explanation (Amazon Bedrock):", "", fenced(plain_segments(result.summary)), ""]
        lines.append("- Evidence cited: " + ", ".join(md_escape(e) if " " in e else _code(e) for e in result.evidence_ids))
        lines.append("- Fix cited: " + (_code(result.cited_fix) if result.cited_fix else "none"))
        lines += ["", "Limitations stated by the model:", "", fenced(plain_segments(result.limitations)), ""]
    else:
        lines.append(f"- AI explanation unavailable: {md_escape(result.error or result.status)}")
        if delta:
            lines += ["", "Template summary (deterministic, not AI-generated):", "", template_summary(comparison, delta, fixes), ""]
    return lines


def build_report(
    comparison: Comparison,
    fixes: tuple[FixCandidate, ...] = (),
    simulation: FixCandidate | None = None,
    explanations: tuple[ExplanationResult, ...] = (),
    generated_at: str | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    base, prop = comparison.baseline.snapshot, comparison.proposal.snapshot
    lines = [
        "# AttackGraph AI comparison report",
        "",
        "> **Synthetic configuration JSON.** Static analysis of declared facts. No configuration was deployed or "
        "executed, and no represented account was contacted. Amazon Bedrock is called only to explain results.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Generated | {generated_at} |",
        f"| Analysis ID | {_code(comparison.analysis_id)} |",
        f"| Engine | {ENGINE_VERSION} |",
        f"| Security model | {_code(MODEL_VERSION)} |",
        f"| Schema | {SCHEMA_VERSION} |",
        _snapshot_row("Baseline", base),
        _snapshot_row("Proposal", prop),
        f"| Coverage | {'complete' if comparison.complete else 'incomplete'} |",
        "",
        "## Result",
        "",
        f"**{verdict_text(comparison)}**",
        "",
        f"- High-risk findings: baseline {comparison.baseline.high_risk_count}, proposal {comparison.proposal.high_risk_count}"
        + (f", simulated fix {simulation.simulated.high_risk_count}" if simulation else ""),
        f"- Added {comparison.count('added')}, removed {comparison.count('removed')}, unchanged {comparison.count('unchanged')}, "
        f"inconclusive {comparison.count('inconclusive')}",
        "- Severity is a demo rubric (reachable privileged role or readable protected object = High), not CVSS or an AWS rating.",
        "",
        "## Coverage",
        "",
        *_coverage_lines("Baseline", comparison.baseline),
        *_coverage_lines("Proposal", comparison.proposal),
        "",
        *[f"- {md_escape(note)}" for note in comparison.proposal.coverage.notes],
        "",
        "## Configuration changes",
        "",
    ]
    if comparison.fact_changes:
        lines += ["| Fact | Statement | Baseline | Proposal | Pointer (proposal) |", "|---|---|---|---|---|"]
        for change in comparison.fact_changes:
            ptr = change.proposal.pointer if change.proposal else change.baseline.pointer
            flag = " (newly enabled grant)" if change.newly_enabled else ""
            lines.append(
                f"| {_code(change.fact_id)} | {md_escape(change.describe())}{flag} | {change.before} | {change.after} | {_code(ptr)} |"
            )
    else:
        lines.append("No fact changed.")
    for change in comparison.config_changes:
        lines.append(f"- {change.kind.replace('_', ' ')}: {md_escape(change.describe())}")
    lines += ["", "## Findings", ""]
    if comparison.deltas:
        lines += ["| Status | Severity | Finding | Baseline | Proposal |", "|---|---|---|---|---|"]
        for delta in comparison.deltas:
            status = STATUS_WORDS[delta.status] + (" (provisional)" if delta.provisional else "")
            lines.append(f"| {status} | {delta.severity} | {md_escape(delta.describe())} | {delta.baseline_state} | {delta.proposal_state} |")
        lines.append("")
        for delta in comparison.deltas:
            lines += _finding_section(comparison, delta)
    else:
        lines.append("No modelled high-risk access in either snapshot.")
        lines.append("")

    lines += ["## Expected-access checks", ""]
    checks = {r.check.id: r for r in comparison.proposal.expected_access}
    if checks:
        header = "| Check | Relationship | Baseline | Proposal |" + (" Simulated |" if simulation else "")
        lines += [header, "|---|---|---|---|" + ("---|" if simulation else "")]
        for check_id, result in checks.items():
            before = comparison.baseline.expected_result(check_id)
            row = (
                f"| {_code(check_id)} | {_code(result.check.principal)} {result.check.relationship.replace('_', ' ')} "
                f"{_code(result.check.target)} | {before.result if before else 'not declared'} | {result.result} |"
            )
            if simulation:
                after = simulation.simulated.expected_result(check_id)
                row += f" {after.result if after else 'n/a'} |"
            lines.append(row)
    else:
        lines.append("No expected-access checks declared.")
    lines.append("")

    lines += ["## Fix simulation", ""]
    if fixes:
        lines += [
            "| Candidate | Removes | Remaining high-risk | Expected access failing | Coverage after | Rank |",
            "|---|---|---|---|---|---|",
        ]
        for fix in fixes:
            removes = ", ".join(_code(k) for k in fix.removed) or "nothing"
            lines.append(
                f"| {_code(fix.id)} | {removes} | {len(fix.remaining) + len(fix.now_inconclusive)} | {fix.failed_expected} | "
                f"{'complete' if fix.coverage_complete else 'incomplete'} | {fix.rank or 'not verified'} |"
            )
        lines.append("")
    else:
        lines += ["No newly enabled grant participates in a proposal finding, so no single-permission fix was tested.", ""]
    if simulation:
        verified = [k for k in simulation.removed if simulation.verified_for(k)]
        lines += [
            f"Simulated: {_code(simulation.fact_id)} set from `true` to `false` on an in-memory copy of the proposal "
            f"(record kept at {_code(simulation.proposal_fact.pointer)}). The uploaded files were not modified.",
            "",
            f"- Removed findings: {', '.join(_code(k) for k in simulation.removed) or 'none'}",
            f"- Remaining findings: {', '.join(_code(k) for k in simulation.remaining) or 'none'}",
            f"- Inconclusive after the change: {', '.join(_code(k) for k in simulation.now_inconclusive) or 'none'}",
            f"- Coverage after the change: {'complete' if simulation.coverage_complete else 'incomplete'}",
            "- Verified in this model for: " + (", ".join(_code(k) for k in verified) if verified else "none"),
        ]
        for check_id, before, after in simulation.expected_changes:
            lines.append(f"- Expected access {_code(check_id)} changes: {before} → {after}")
        lines.append("")
    else:
        lines += ["No fix was simulated in this session.", ""]

    lines += ["## AI explanations", ""]
    if explanations:
        for result in explanations:
            lines += _explanation_lines(result, comparison, fixes)
    else:
        lines += ["No AI explanation was requested for this analysis.", ""]

    lines += ["## Nodes", "", "| ID | Kind | Account | Label (display only) |", "|---|---|---|---|"]
    for node_id in sorted(set(base.nodes) | set(prop.nodes)):
        node = prop.nodes.get(node_id) or base.nodes[node_id]
        lines.append(f"| {_code(node_id)} | {KIND_TITLES[node.kind]} | {_code(node.account_id)} | {md_escape(node.label)} |")
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in LIMITATIONS]
    lines.append("")
    return "\n".join(lines)
