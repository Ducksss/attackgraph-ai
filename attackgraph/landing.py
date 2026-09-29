"""Landing page sections: why the tool is needed, how it works, and why to trust it.

Every number and diagram on the page comes from the engine's analysis of the
bundled flagship scenario; nothing here is a marketing figure.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from . import web
from .pipeline import PipelineResult
from .simulate import best_fix_for
from .story import build_story, label

esc, icon = web.esc, web.icon
RECORDED = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "recorded-explanation.json"

CSS = """
<style>
.ag-hero { position: relative; isolation: isolate; text-align: center; padding: 64px 12px 24px; }
.ag-hero::before { content: ""; position: absolute; inset: 180px 0 -20px; z-index: -1;
  background: radial-gradient(#dcdce4 1px, transparent 1px) 0 0 / 18px 18px;
  -webkit-mask-image: radial-gradient(60% 60% at 50% 55%, #000 30%, transparent 75%); mask-image: radial-gradient(60% 60% at 50% 55%, #000 30%, transparent 75%); }
.ag-hero .ag-h1 { max-width: 980px; margin-left: auto; margin-right: auto; }

.ag-flow { position: relative; display: grid; grid-template-columns: 150px 48px minmax(360px, 1.4fr) 56px 118px 56px minmax(250px, 1fr);
  align-items: center; margin: 52px auto 0; max-width: 1180px; text-align: left; }
.ag-flow-col { height: 326px; display: flex; flex-direction: column; justify-content: center; position: relative; grid-row: 1; }
.ag-wires { width: 100%; height: 326px; display: block; grid-row: 1; }
.ag-flow .c1 { grid-column: 1; } .ag-flow .c2 { grid-column: 2; } .ag-flow .c3 { grid-column: 3; } .ag-flow .c4 { grid-column: 4; }
.ag-flow .c5 { grid-column: 5; } .ag-flow .c6 { grid-column: 6; } .ag-flow .c7 { grid-column: 7; }
.ag-flow-pill { background: var(--ag-surface); border: 1px solid var(--ag-line); border-radius: 12px; padding: 10px 12px; box-shadow: var(--ag-shadow); }
.ag-flow-pill .ag-small { display: block; margin-top: 2px; }
.ag-flow-pill strong { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: var(--ag-text); }
.ag-flow-pill strong .ag-icon { color: var(--ag-accent); font-size: 18px; }
.ag-flow-chips { gap: 10px; }
.ag-flow-chip { height: 38px; box-sizing: border-box; display: flex; align-items: center; gap: 8px; padding: 0 12px; border: 1px solid var(--ag-line);
  border-radius: 10px; background: var(--ag-surface); font-size: 13.5px; color: var(--ag-body); white-space: nowrap; overflow: hidden;
  box-shadow: var(--ag-shadow); }
.ag-flow-chip .ag-icon { font-size: 17px; color: var(--ag-green); flex: none; }
.ag-flow-chip.changed { border-color: var(--ag-amber-line); background: var(--ag-amber-soft); color: var(--ag-text); font-weight: 500; }
.ag-flow-chip.changed .ag-icon { color: var(--ag-amber); }
.ag-flow-chip .ag-badge { margin-left: auto; flex: none; }
.ag-flow-chip span.t { overflow: hidden; text-overflow: ellipsis; }
.ag-flow-core { align-items: center; gap: 10px; }
.ag-core-tile { width: 88px; height: 88px; border-radius: 22px; display: grid; place-items: center; color: #fff;
  background: linear-gradient(145deg, #7b7ef6, #4f46e5); box-shadow: 0 18px 32px rgba(79, 70, 229, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.35); }
.ag-core-tile .ag-icon { font-size: 44px; }
.ag-core-label { font-size: 13px; font-weight: 600; color: var(--ag-text); text-align: center; line-height: 1.35; white-space: nowrap; }
.ag-core-label .ag-small { display: block; font-weight: 400; }
.ag-flow-out { gap: 20px; }
.ag-flow-card { height: 124px; box-sizing: border-box; border: 1px solid var(--ag-line); border-radius: 12px; padding: 14px 16px; background: var(--ag-surface);
  box-shadow: var(--ag-shadow); display: flex; flex-direction: column; justify-content: center; gap: 6px; }
.ag-flow-card.risk { border-color: var(--ag-amber-line); box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.12), var(--ag-shadow); }
.ag-flow-card.good { border-color: var(--ag-green-line); }
.ag-flow-card .ag-flow-title { font-size: 15px; font-weight: 500; line-height: 1.4; color: var(--ag-text); }
.ag-flow-card .ag-flow-note { font-size: 13px; line-height: 1.4; color: var(--ag-muted); margin-top: -2px; }

.ag-proof { margin-top: 64px; border: 1px solid var(--ag-line); border-radius: 16px; background: var(--ag-surface); overflow: hidden; }
.ag-proof-quote { margin: 0; padding: 36px 40px 28px; font-size: clamp(20px, 2.1vw, 28px); line-height: 1.45; letter-spacing: -0.01em; color: var(--ag-text);
  background: var(--ag-surface-2); border-bottom: 1px solid var(--ag-line); }
.ag-proof-quote .ag-soft { color: var(--ag-soft); }
.ag-proof-stats { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; padding: 20px; background: var(--ag-surface-2); }
.ag-proof-stat { background: var(--ag-surface); border: 1px solid var(--ag-line-2); border-radius: 12px; padding: 18px; }
.ag-proof-stat b { display: block; font-size: 24px; font-weight: 500; letter-spacing: -0.02em; color: var(--ag-text); font-variant-numeric: tabular-nums; }
.ag-proof-stat span { display: block; margin-top: 4px; color: var(--ag-muted); font-size: 14px; line-height: 1.45; }
.ag-proof-note { padding: 0 20px 18px; background: var(--ag-surface-2); color: var(--ag-soft); font-size: 13px; }

.ag-grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 40px 56px; margin-top: 36px; }
.ag-benefit { display: flex; gap: 18px; align-items: flex-start; }
.ag-benefit-icon { flex: none; width: 56px; height: 56px; border-radius: 12px; border: 1px solid var(--ag-line); background: var(--ag-surface);
  display: grid; place-items: center; box-shadow: var(--ag-shadow); }
.ag-benefit-icon .ag-icon { font-size: 28px; background: linear-gradient(160deg, #818cf8, #4f46e5); -webkit-background-clip: text; background-clip: text;
  color: transparent; }
.ag-benefit h3 { margin: 2px 0 6px; padding: 0; font-size: 22px; font-weight: 500; letter-spacing: -0.01em; color: var(--ag-text); }
.ag-benefit p { margin: 0; color: var(--ag-muted); font-size: 16px; line-height: 1.6; }

.ag-bento { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 36px; }
.ag-bento-cell { background: var(--ag-surface-2); border: 1px solid var(--ag-line-2); border-radius: 16px; padding: 28px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.ag-bento-cell.wide { grid-column: 1 / -1; }
.ag-bento-cell h3 { margin: 0; padding: 0; font-size: 22px; font-weight: 500; letter-spacing: -0.01em; color: var(--ag-text); }
.ag-bento-cell > p { margin: 0; color: var(--ag-muted); font-size: 16px; line-height: 1.6; }
.ag-bento-visual { margin-top: 18px; background: var(--ag-surface); border: 1px solid var(--ag-line); border-radius: 12px; padding: 16px; box-shadow: var(--ag-shadow); }
.ag-quote { margin: 0; font-size: 16px; line-height: 1.65; color: var(--ag-body); }
.ag-fixrow { display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch; }
.ag-fixrow .ag-stat { flex: 1 1 180px; }
.ag-fixrow .ag-btn { align-self: center; }

.ag-trust { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 48px; align-items: start; margin-top: 88px; scroll-margin-top: 24px; }
.ag-trust .ag-h2 { margin-top: 12px; }

.ag-final { margin-top: 96px; border: 1px solid var(--ag-line); border-radius: 16px; background: var(--ag-surface); text-align: center; padding: 72px 24px 64px;
  background-image: radial-gradient(#e4e4ea 1px, transparent 1px); background-size: 18px 18px; }
.ag-final .ag-h2 { max-width: 760px; margin: 0 auto 12px; }

.ag-dark-footer { margin-top: 96px; border-radius: 16px; padding: 44px 40px 26px; background: #000; color: #a1a1b0; }
.ag-dark-inner { display: grid; grid-template-columns: 1.6fr 1fr 1fr 1fr; gap: 32px; }
.ag-dark-footer .ag-brand { color: #fff !important; }
.ag-dark-footer p { margin: 12px 0 0; font-size: 14px; line-height: 1.6; max-width: 360px; }
.ag-dark-footer h4 { margin: 0 0 12px; color: #fff; font-size: 14px; font-weight: 600; }
.ag-dark-footer ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; font-size: 14px; }
.ag-dark-footer a { color: #a1a1b0 !important; text-decoration: none !important; }
.ag-dark-footer a:hover { color: #fff !important; }
.ag-dark-legal { margin-top: 32px; padding-top: 18px; border-top: 1px solid #222; font-size: 13px; color: #6b6b7b; }

@media (max-width: 1060px) {
  .ag-flow { grid-template-columns: 1fr; gap: 12px; max-width: 520px; }
  .ag-flow > .ag-wires { display: none; }
  .ag-flow-col { height: auto; grid-row: auto; }
  .ag-flow .c1, .ag-flow .c3, .ag-flow .c5, .ag-flow .c7 { grid-column: 1; }
  .ag-flow-core { flex-direction: row; justify-content: center; }
  .ag-core-tile { width: 64px; height: 64px; border-radius: 16px; }
  .ag-core-tile .ag-icon { font-size: 32px; }
  .ag-flow-card { height: auto; }
  .ag-flow-chip { white-space: normal; height: auto; min-height: 38px; padding: 8px 12px; }
}
@media (max-width: 900px) {
  .ag-proof-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 480px) {
  .ag-proof-stats { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 900px) {
  .ag-grid2, .ag-bento, .ag-trust { grid-template-columns: 1fr; }
  .ag-dark-inner { grid-template-columns: 1fr 1fr; }
}
</style>
"""

CHIP_TEXT = {
    "iam_pass_role_to_lambda": "Pass {target} to Lambda",
    "lambda_create_function": "Create {via}",
    "lambda_invoke_function": "Invoke {via}",
    "controls_workload_code": "Control the function's code",
    "role_trusts_lambda_service": "{target} trusts Lambda",
    "same_account": "One AWS account",
    "policy_controls_resolved": "No unresolved restrictions",
    "s3_get_object": "Read {target}",
}
CHANGE_PHRASES = {
    "iam_pass_role_to_lambda": "widens iam:PassRole",
    "s3_get_object": "grants s3:GetObject",
    "lambda_create_function": "grants lambda:CreateFunction",
    "lambda_invoke_function": "grants lambda:InvokeFunction",
    "role_trusts_lambda_service": "edits a role trust policy",
    "controls_workload_code": "changes who owns the code",
}
FIX_PHRASES = {
    "iam_pass_role_to_lambda": "Revoke the new iam:PassRole grant",
    "s3_get_object": "Revoke the new s3:GetObject grant",
    "lambda_create_function": "Revoke the new lambda:CreateFunction grant",
    "lambda_invoke_function": "Revoke the new lambda:InvokeFunction grant",
    "role_trusts_lambda_service": "Revert the role trust change",
    "controls_workload_code": "Revert the code ownership change",
}
CHIP_H, CHIP_GAP, FLOW_H = 38, 10, 326
CARD_H, CARD_GAP = 124, 16


def load_recorded(comparison, path: Path = RECORDED) -> dict | None:
    """The recorded Bedrock reply, only if it belongs to exactly this analysis and finding."""
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    delta = comparison.deltas[0] if comparison.deltas else None
    if delta is None or record.get("analysis_id") != comparison.analysis_id or record.get("finding_id") != delta.id:
        return None
    return record


WIRE_STROKES = {"": ("#d6d7f5", 1.5), "hot": ("#f59e0b", 2), "ok": ("#86efac", 2)}


def _wires(starts: list[float], ends: list[float], classes: list[str], column: int) -> str:
    """Curved connectors between two flow columns.

    Drawn as an image of an SVG because Streamlit's HTML sanitiser removes
    inline <svg> elements. Highlighted wires are drawn last so they sit on top.
    """
    ordered = sorted(zip(starts, ends, classes), key=lambda item: item[2] != "")
    paths = "".join(
        f'<path d="M0,{a:.1f} C50,{a:.1f} 50,{b:.1f} 100,{b:.1f}" fill="none" stroke="{WIRE_STROKES[c][0]}" '
        f'stroke-width="{WIRE_STROKES[c][1]}" vector-effect="non-scaling-stroke"/>'
        for a, b, c in ordered
    )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 {FLOW_H}" preserveAspectRatio="none">{paths}</svg>'
    data = base64.b64encode(svg.encode()).decode()
    return f'<img class="ag-wires c{column}" src="data:image/svg+xml;base64,{data}" alt="" aria-hidden="true">'


def pipeline_flow(result: PipelineResult) -> str:
    """Hero diagram: the change, the conditions it completes, the engine, and what comes out."""
    comparison = result.comparison
    delta = comparison.deltas[0]
    story = build_story(comparison, delta)
    snapshot = comparison.proposal.snapshot
    candidate = story.steps[0].candidate
    names = {"target": label(snapshot, candidate.target), "via": label(snapshot, candidate.via)}
    conditions = story.steps[0].conditions
    fix = best_fix_for(result.fixes, delta.id)

    chips = []
    for c in conditions:
        text = CHIP_TEXT[c.key].format(**names)
        mark = '<span class="ag-badge new">New</span>' if c.change else ""
        chips.append(
            f'<div class="ag-flow-chip{" changed" if c.change else ""}">{icon("check_circle")}<span class="t">{esc(text)}</span>{mark}</div>'
        )
    ys = [CHIP_H / 2 + i * (CHIP_H + CHIP_GAP) for i in range(len(conditions))]
    offset = (FLOW_H - (len(conditions) * CHIP_H + (len(conditions) - 1) * CHIP_GAP)) / 2
    ys = [y + offset for y in ys]
    mid = FLOW_H / 2
    hot = ["hot" if c.change else "" for c in conditions]

    change = story.changes[0] if story.changes else None
    pill_sub = CHANGE_PHRASES.get(change.key, "changes one fact") if change else "proposed configuration"
    pill = (
        f'<div class="ag-flow-pill"><strong>{icon("merge")}Pull request</strong>'
        f'<span class="ag-small">{esc(pill_sub)}</span></div>'
    )
    top = (FLOW_H - (2 * CARD_H + CARD_GAP)) / 2
    outs = [top + CARD_H / 2, top + CARD_H + CARD_GAP + CARD_H / 2]
    risk_card = (
        '<div class="ag-flow-card risk"><span class="ag-badge amber" style="align-self:flex-start">New path found</span>'
        f'<div class="ag-flow-title">{esc(story.headline)}</div></div>'
    )
    if fix is not None:
        kept = sum(1 for r in fix.expected_after if r.result == "pass")
        revoked = next((c for c in conditions if c.fact_id == fix.fact_id), None)
        title = FIX_PHRASES.get(revoked.key, f"Revoke {fix.fact_id}") if revoked else f"Revoke {fix.fact_id}"
        fix_card = (
            '<div class="ag-flow-card good"><span class="ag-badge green" style="align-self:flex-start">Verified fix</span>'
            f'<div class="ag-flow-title">{esc(title)}</div>'
            f'<div class="ag-flow-note">Path closed. Normal access kept: {kept} of {len(fix.expected_after)}.</div></div>'
        )
    else:
        fix_card = '<div class="ag-flow-card"><div class="ag-flow-title">No single revocation closes the path</div></div>'
    held = sum(1 for c in conditions if c.state == "true")
    summary = (
        f"A pull request flips {change.fact_id if change else 'one fact'}. The engine checks {len(conditions)} conditions; "
        f"{held} hold, so it finds a new path: {story.headline}. Revoking the change is verified to close it."
    )
    return (
        f'<div class="ag-flow" role="img" aria-label="{esc(summary)}">'
        f'<div class="ag-flow-col c1">{pill}</div>'
        + _wires([mid] * len(ys), ys, hot, 2)
        + f'<div class="ag-flow-col ag-flow-chips c3">{"".join(chips)}</div>'
        + _wires(ys, [mid] * len(ys), hot, 4)
        + f'<div class="ag-flow-col ag-flow-core c5"><div class="ag-core-tile">{icon("conversion_path")}</div>'
        f'<div class="ag-core-label">AttackGraph engine<span class="ag-small">{len(conditions)} conditions,<br>all required</span></div></div>'
        + _wires([mid, mid], outs, ["hot", "ok" if fix else ""], 6)
        + f'<div class="ag-flow-col ag-flow-out c7">{risk_card}{fix_card}</div>'
        + "</div>"
    )


def hero(result: PipelineResult) -> str:
    return (
        '<section class="ag-hero" id="top">'
        f'<span class="ag-pill">{icon("verified_user")}Pre-deployment review for cloud permission changes</span>'
        '<h1 class="ag-h1">Ship permission changes without shipping admin access.</h1>'
        '<p class="ag-lead">AttackGraph AI finds new routes to admin roles and sensitive data in a cloud change, then proves the fix.</p>'
        f'<div class="ag-cta"><a class="ag-btn ag-btn-primary" href="{web.DEMO}">Open the live demo</a>'
        '<a class="ag-btn ag-btn-ghost" href="#why">Why it matters</a></div>'
        + pipeline_flow(result)
        + "</section>"
    )


def proof(result: PipelineResult) -> str:
    comparison = result.comparison
    delta = comparison.deltas[0]
    story = build_story(comparison, delta)
    fix = best_fix_for(result.fixes, delta.id)
    held = sum(1 for c in story.conditions if c.state == "true")
    kept = sum(1 for r in fix.expected_after if r.result == "pass") if fix else 0
    stats = [
        (str(len(comparison.fact_changes)), "permission changed in the pull request"),
        (f"{held} of {len(story.conditions)}", "conditions for the admin route now hold"),
        (f"{comparison.baseline.high_risk_count} → {comparison.proposal.high_risk_count}", "high-risk paths, baseline to proposed"),
        ("1 revocation" if fix else "None", "closes the path, verified in the model"),
        (f"{kept} of {len(fix.expected_after)}" if fix else "-", "normal access checks still pass after the fix"),
    ]
    cells = "".join(f'<div class="ag-proof-stat"><b>{esc(v)}</b><span>{esc(t)}</span></div>' for v, t in stats)
    return (
        '<div class="ag-proof">'
        '<p class="ag-proof-quote">A reviewer sees one changed line. <span class="ag-soft">The risk lives in what that line completes: '
        "a build pipeline that can hand itself the deployment admin role.</span></p>"
        f'<div class="ag-proof-stats">{cells}</div>'
        '<div class="ag-proof-note">Computed by the engine from the bundled demo snapshots. Synthetic data, no real account.</div>'
        "</div>"
    )


WHY = (
    ("difference", "Diffs hide paths", "Widening iam:PassRole reads as a one-word edit. Whether it hands out admin depends on grants made long before."),
    (
        "join",
        "Single checks miss combinations",
        "Each permission can look harmless alone. Passing a role, creating a function, invoking it and owning its code together mean running as admin.",
    ),
    ("build", "Fixes are guesswork", "Revoke the wrong grant and the deploy breaks. Revoke nothing and the path stays open."),
    ("help", "Unknowns get read as safe", "When a permission is not described, reviews tend to assume it is absent. AttackGraph AI calls it unknown and says so."),
)


def why() -> str:
    cards = "".join(
        f'<div class="ag-benefit"><div class="ag-benefit-icon">{icon(g)}</div><div><h3>{esc(t)}</h3><p>{esc(b)}</p></div></div>'
        for g, t, b in WHY
    )
    return (
        '<div class="ag-hatch"></div>'
        + web.section_head(
            "Permission reviews miss paths,",
            soft="because risk lives in combinations.",
            sub="The question a reviewer needs answered: what new access does this change create, and which permission should go?",
            anchor="why",
        )
        + f'<div class="ag-grid2">{cards}</div>'
    )


def how(result: PipelineResult, recorded: dict | None) -> str:
    comparison = result.comparison
    delta = comparison.deltas[0]
    story = build_story(comparison, delta)
    fix = best_fix_for(result.fixes, delta.id)
    if recorded:
        first = recorded["summary"].split(". ", 1)[0].rstrip(".") + "."
        quote = (
            f'<span class="ag-badge green">Recorded Nova Pro reply</span><p class="ag-quote" style="margin-top:10px">“{esc(first)}”</p>'
            f'<div class="ag-small" style="margin-top:8px">First sentence of a live reply: {esc(recorded["model_id"])}, request '
            f'{esc(recorded["request_id"])}, {esc(recorded["created_at"][:10])}. The full reply is in the live demo.</div>'
        )
    else:
        quote = '<p class="ag-quote">Run the app with AWS credentials to generate an explanation.</p>'
    fix_visual = ""
    if fix is not None:
        kept = sum(1 for r in fix.expected_after if r.result == "pass")
        fix_visual = (
            '<div class="ag-fixrow">'
            + web.stats(
                [
                    ("High-risk paths", f"{comparison.proposal.high_risk_count} → {fix.simulated.high_risk_count}", "Proposed, then after the fix", "good"),
                    ("Normal access", f"{kept} of {len(fix.expected_after)}", "Expected-access checks that still pass", "good"),
                ],
                columns=2,
            ).replace('class="ag-stats two"', 'class="ag-stats two" style="flex:2 1 360px;margin:0"')
            + f'<a class="ag-btn ag-btn-primary" href="{web.DEMO}">Open the live demo</a></div>'
        )
    cells = (
        '<div class="ag-bento-cell wide"><h3>Map every route</h3>'
        "<p>Two explicit rules link permissions into routes from an entry point to protected roles and data. "
        "A missing fact stays unknown, never safe.</p>"
        f'<div class="ag-bento-visual">{web.path(story, compact=True)}</div></div>'
        '<div class="ag-bento-cell"><h3>Explain it with Amazon Bedrock</h3>'
        "<p>Nova Pro writes the explanation from placeholder IDs. It cannot add findings, change severity or invent fixes.</p>"
        f'<div class="ag-bento-visual">{quote}</div></div>'
        '<div class="ag-bento-cell"><h3>Test the fix before you touch infrastructure</h3>'
        "<p>Revoke the new permission on a copy, rerun the whole analysis, and confirm the route is gone while normal access "
        "still works.</p>"
        f'<div class="ag-bento-visual">{fix_visual}</div></div>'
    )
    return (
        web.section_head("Find it, explain it, fix it.", soft="Every step traceable.", anchor="how")
        + f'<div class="ag-bento">{cells}</div>'
    )


def trust() -> str:
    chips = "".join(f'<span class="ag-chip">{icon(g)}{esc(t)}</span>' for g, t in web.TRUST_CHIPS)
    faq = "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in web.FAQ)
    return (
        '<div class="ag-trust" id="trust"><div>'
        f'<span class="ag-tag">{icon("shield")}Trust and limits</span>'
        '<h2 class="ag-h2">Built to be checked, <span class="ag-soft">not trusted.</span></h2>'
        '<p class="ag-sub">Every result traces back to a line in the input files, and the limits are stated up front.</p>'
        f'<div class="ag-chips">{chips}</div></div>'
        f'<div class="ag-faq">{faq}</div></div>'
    )


def final_cta() -> str:
    return (
        '<div class="ag-final">'
        '<h2 class="ag-h2">See the path before it ships. <span class="ag-soft">It takes one click.</span></h2>'
        '<p class="ag-sub" style="margin:0 auto">No sign-up. Synthetic data only.</p>'
        f'<div class="ag-cta"><a class="ag-btn ag-btn-primary" href="{web.DEMO}">Open the live demo</a></div>'
        "</div>"
    )


def footer(hosted: bool) -> str:
    ai = "No AI calls on this hosted page" if hosted else "Live Amazon Bedrock explanations"
    return (
        '<footer class="ag-dark-footer"><div class="ag-dark-inner"><div>'
        f'<a class="ag-brand" href="{web.LANDING}"><span class="ag-logo">{icon("conversion_path")}</span>AttackGraph AI</a>'
        "<p>Pre-deployment review for cloud permission changes. Built for the AWS Build Beyond Student AI Demo Challenge 2026.</p></div>"
        f'<div><h4>Product</h4><ul><li><a href="{web.LANDING}">Overview</a></li><li><a href="{web.DEMO}">Live demo</a></li>'
        f'<li><a href="{web.LANDING}#trust">Trust and limits</a></li></ul></div>'
        "<div><h4>Built with</h4><ul><li>Amazon Bedrock (Nova Pro)</li><li>NetworkX</li><li>Streamlit</li></ul></div>"
        f"<div><h4>Scope</h4><ul><li>Synthetic data only</li><li>Nothing is deployed</li><li>{esc(ai)}</li></ul></div></div>"
        '<div class="ag-dark-legal">A static analysis of declared facts. Results describe the synthetic model, not a real AWS account.</div>'
        "</footer>"
    )


def page(result: PipelineResult, hosted: bool, recorded_path: Path = RECORDED) -> str:
    recorded = load_recorded(result.comparison, recorded_path)
    return (
        web.nav(web.LANDING)
        + hero(result)
        + proof(result)
        + why()
        + how(result, recorded)
        + trust()
        + final_cta()
        + footer(hosted)
    )


def demo_header() -> str:
    return (
        '<div class="ag-section ag-center" id="demo" style="margin-top:48px">'
        f'<span class="ag-tag">{icon("play_circle")}Live demo</span>'
        '<h1 class="ag-h1">Watch one permission <span class="ag-soft line">become an admin path.</span></h1>'
        '<p class="ag-lead">The real engine on bundled synthetic snapshots. Pick a scenario; everything below is computed '
        "from the files, not scripted.</p></div>"
    )

