"""Page sections shared by the Streamlit app and the static hosted build.

Every function returns an HTML string built from engine objects. The caller
places it: a keyed Streamlit container locally, a static card on Vercel.
"""

from __future__ import annotations

from . import web
from .compare import Comparison, FindingDelta
from .pipeline import PipelineResult
from .simulate import FixCandidate, best_fix_for
from .story import Story, build_story, expected_text, involves_pass_role, is_potential

STATUS_BADGES = {"added": "amber", "removed": "green", "unchanged": "gray", "inconclusive": "amber"}
STATUS_WORDS = {"added": "New path", "removed": "Path closed", "unchanged": "Unchanged", "inconclusive": "Unresolved"}
MODEL_NAMES = {"nova-pro": "Amazon Nova Pro", "nova-2-lite": "Amazon Nova 2 Lite", "nova-lite": "Amazon Nova Lite", "claude": "Claude"}


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def model_name(model_id: str) -> str:
    return next((name for key, name in MODEL_NAMES.items() if key in model_id), model_id)


def invalid(result: PipelineResult) -> str:
    errors = [
        (f"{loaded.source_name} {issue.pointer or '(file)'}", issue.message)
        for loaded in (result.baseline, result.proposal)
        for issue in loaded.issues
    ]
    return web.verdict(
        "error",
        "These files can't be analysed yet",
        f"{plural(len(errors), 'field error')} found. Neither file is analysed until both are valid.",
        errors,
    )


def verdict(result: PipelineResult) -> str:
    comparison = result.comparison
    added = [d for d in comparison.deltas if d.status == "added"]
    removed = comparison.count("removed")
    resolved = "Every relationship resolved. Complete for the declared synthetic model, not for a real AWS account."
    if comparison.verdict == "incomplete":
        unresolved = len(comparison.baseline.coverage.issues) + len(comparison.proposal.coverage.issues)
        return web.verdict(
            "unknown",
            "Analysis incomplete",
            f"{plural(unresolved, 'relationship')} could not be resolved, so nothing here is a safe verdict. "
            "The unresolved condition is marked below.",
        )
    if added:
        kinds = {d.impact for d in added}
        target = "role" if kinds == {"privileged_role_use"} else "data" if kinds == {"sensitive_object_read"} else "resource"
        first = build_story(comparison, added[0])
        return web.verdict(
            "risk",
            f"{plural(len(added), 'new path')} to a protected {target}",
            f"{first.headline}. Nothing was deployed: this is a static check of two synthetic snapshots.",
        )
    if removed:
        return web.verdict("safe", f"The change closes {plural(removed, 'path')} and opens none", resolved)
    return web.verdict("safe", "No new paths to protected resources", resolved)


def stats(result: PipelineResult, sim: FixCandidate | None = None) -> str:
    comparison = result.comparison
    added = [d for d in comparison.deltas if d.status == "added"]
    before, after = comparison.baseline.high_risk_count, comparison.proposal.high_risk_count
    risk_note = f"Baseline {before}, proposed {after}"
    if sim:
        risk_note += f", after simulated fix {sim.simulated.high_risk_count}"
    unresolved = len(comparison.proposal.coverage.issues) + len(comparison.baseline.coverage.issues)
    fix = best_fix_for(result.fixes, added[0].id) if added else None
    if not comparison.complete:
        fix_card = ("Verified fix", "Not yet", "A fix cannot be verified while a condition is unknown", "")
    elif fix:
        kept = sum(1 for r in fix.expected_after if r.result == "pass")
        fix_card = ("Verified fix", "1 revocation", f"Normal access kept: {kept} of {len(fix.expected_after)}", "good")
    elif added:
        fix_card = ("Verified fix", "None found", "No single revocation closes the path", "risk")
    else:
        fix_card = ("Verified fix", "Not needed", "No new path to fix", "")
    first_change = comparison.fact_changes[0].fact_id if comparison.fact_changes else "No fact changed"
    return web.stats(
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
                "Every relationship resolved" if comparison.complete else plural(unresolved, "unresolved relationship"),
                "good" if comparison.complete else "risk",
            ),
            fix_card,
        ]
    )


def change_card(comparison: Comparison, story: Story) -> str:
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
    return (
        web.card_head("difference", "The change", badge)
        + f'<p class="ag-note">{web.esc(intro)}</p>'
        + web.change_block(story)
        + extra
        + glossary
    )


def path_card(story: Story, sim: FixCandidate | None = None) -> str:
    delta = story.delta
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
    return web.card_head("conversion_path", title) + f'<p class="ag-note">{web.esc(note)}</p>' + web.path(story, mode) + blocked


def conditions_card(story: Story) -> str:
    held = sum(1 for c in story.conditions if c.state == "true")
    title, lead = {
        "added": ("Why the route works", "A route only counts when every condition holds. The changed one was the missing piece."),
        "unchanged": ("Why the route works", "A route only counts when every condition holds."),
        "removed": ("What the route needed", "Every condition held in the first snapshot. The second one takes away the changed one."),
        "inconclusive": ("What is unresolved", "One condition is unknown, so the engine will not call this route open or closed."),
    }[story.delta.status]
    return (
        web.card_head("checklist", title, f'<span class="ag-badge gray">{held} of {len(story.conditions)} hold</span>')
        + f'<p class="ag-note">{web.esc(lead)}</p>'
        + web.conditions(story)
    )


def ai_intro(model_id: str) -> str:
    return (
        web.card_head("auto_awesome", "Why it matters", '<span class="ag-badge green">Amazon Bedrock</span>')
        + f'<p class="ag-note">{web.esc(model_name(model_id))} explains the evidence in plain English. It sees '
        "placeholder IDs only and cannot change the result.</p>"
    )


def fix_blocker(result: PipelineResult, delta: FindingDelta) -> str | None:
    """A note explaining why no fix can be simulated, or None when one can."""
    if delta.proposal is None:
        return "This path only exists in the first snapshot, so there is nothing to fix."
    if is_potential(delta) or delta.status == "inconclusive":
        return "No fix can be verified while a condition is unknown. Declare the fact as true or false, then compare again."
    if not result.fixes:
        reason = "The access already existed in the baseline." if delta.status == "unchanged" else "No newly enabled grant is on this route."
        return f"No single-permission fix to test. {reason}"
    return None


def fix_intro(chosen: FixCandidate, best: FixCandidate | None, story: Story) -> str:
    condition = next((c for c in story.conditions if c.fact_id == chosen.fact_id), None)
    human = condition.text if condition else chosen.proposal_fact.describe()
    warning = (
        '<p class="ag-note">No single revocation closes this path: another route remains after each one.</p>' if best is None else ""
    )
    return warning + (
        f'<p class="ag-note">Revoke <span class="ag-mono">{web.esc(chosen.fact_id)}</span> ({web.esc(human)}) on an '
        "in-memory copy of the proposal, then rerun the whole analysis.</p>"
    )


def expected_block(comparison: Comparison, sim: FixCandidate | None = None) -> str:
    snapshot = comparison.proposal.snapshot
    rows = []
    for row in comparison.proposal.expected_access:
        after = sim.simulated.expected_result(row.check.id) if sim else None
        rows.append((expected_text(row.check, snapshot), row.result, after.result if after else None))
    if not rows:
        return ""
    return '<p class="ag-note" style="margin-top:14px">Normal access the fix must keep:</p>' + web.expected_list(rows)


def fix_result(comparison: Comparison, delta: FindingDelta, sim: FixCandidate) -> str:
    kept = sum(1 for r in sim.expected_after if r.result == "pass")
    verified = sim.verified_for(delta.id)
    return web.stats(
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
    ) + (
        '<p class="ag-note"><span class="ag-badge green">Verified in this model</span> The path is gone and every '
        "relationship stayed resolved. The uploaded files are unchanged.</p>"
        if verified
        else '<p class="ag-note"><span class="ag-badge amber">Not verified</span> The finding remains, or coverage became '
        "incomplete after the change.</p>"
    )
