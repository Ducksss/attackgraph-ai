"""Build the static hosted site (deployed on Vercel) from the real engine.

Streamlit needs a long-lived WebSocket server, which Vercel does not run, so
this script renders the same sections as the app into two static pages: the
landing page (why the tool is needed) at / and the live demo at /demo. On the
demo page the scenario tabs and the fix simulation switch between
pre-computed states in the browser.

The hosted page makes no AI calls and accepts no uploads, as the PRD requires
for anonymous visitors. The flagship scenario shows a recorded live Amazon
Nova Pro reply, labelled with its request ID, and only if its analysis ID
still matches the freshly computed analysis. The other scenarios show the
deterministic summary.

Usage:
    python scripts/build_site.py            # writes site/index.html and site/demo/index.html
    python scripts/build_site.py OUT_DIR
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attackgraph import ENGINE_VERSION, MODEL_VERSION, landing, page, web  # noqa: E402
from attackgraph.analysis import Finding  # noqa: E402
from attackgraph.explain import DEFAULT_MODEL_ID, build_packet  # noqa: E402
from attackgraph.render import step_text  # noqa: E402
from attackgraph.report import build_report  # noqa: E402
from attackgraph.scenarios import SCENARIO_LABELS, SCENARIOS, UPLOAD, run_scenario  # noqa: E402
from attackgraph.simulate import best_fix_for  # noqa: E402
from attackgraph.snapshot import POLICY_CONTROLS, UNMODELLED_MECHANISMS  # noqa: E402
from attackgraph.story import build_story, summary  # noqa: E402

RECORDED = ROOT / "docs" / "evidence" / "recorded-explanation.json"
esc = web.esc

SITE_CSS = """
<style>
html, body { background: #f9f9fa; color: #111114; margin: 0; }
body { font-family: "Inter", system-ui, -apple-system, sans-serif; font-size: 16px; line-height: 1.5; -webkit-font-smoothing: antialiased; }
.ag-page { max-width: 1200px; margin: 0 auto; padding: 16px 24px 40px; box-sizing: border-box; }
.ag-scard { background: var(--ag-surface); border: 1px solid var(--ag-line); border-radius: 12px; padding: 22px 22px 18px;
  margin-top: 16px; box-sizing: border-box; min-width: 0; box-shadow: var(--ag-shadow); }
.ag-switch { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px; margin: 0 auto 14px; width: fit-content; max-width: 100%;
  padding: 4px; border: 1px solid var(--ag-line); border-radius: 12px; background: var(--ag-surface); box-shadow: var(--ag-shadow); }
.ag-switch button { font: inherit; font-size: 14.5px; color: var(--ag-body); background: transparent; border: 0; border-radius: 8px;
  padding: 7px 14px; cursor: pointer; }
.ag-switch button:hover { background: var(--ag-surface-2); }
.ag-switch button[aria-selected="true"] { color: #fff; background: #1d1d20; }
.ag-switch button:focus-visible { outline: 2px solid var(--ag-accent); outline-offset: 2px; }
button.ag-btn { font-family: inherit; cursor: pointer; }
.ag-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
.ag-sim-on, .ag-actions .ag-sim-on { display: none; }
.ag-scenario[data-simulated="true"] .ag-sim-on { display: block; }
.ag-scenario[data-simulated="true"] .ag-actions .ag-sim-on { display: inline-flex; }
.ag-scenario[data-simulated="true"] .ag-sim-off { display: none; }
pre.ag-json { background: var(--ag-surface-2); color: var(--ag-body); border: 1px solid var(--ag-line); border-radius: 10px; padding: 12px 14px;
  margin: 0 14px 14px; overflow: auto; max-height: 360px; font-family: var(--ag-mono); font-size: 12px; line-height: 1.5; white-space: pre; }
pre.ag-json.flat { margin: 14px 0 0; max-height: none; }
.ag-evidence { margin-top: 16px; border: 1px solid var(--ag-line); border-radius: 12px; background: var(--ag-surface); box-shadow: var(--ag-shadow); }
.ag-evidence > summary { cursor: pointer; list-style: none; padding: 14px 18px; font-weight: 500; display: flex; align-items: center; gap: 8px; }
.ag-evidence > summary::-webkit-details-marker { display: none; }
.ag-evidence > summary .ag-icon { color: var(--ag-accent); }
.ag-evidence-body { padding: 0 18px 18px; }
.ag-evidence h4 { font-size: 16px; font-weight: 600; margin: 20px 0 8px; }
.ag-table-wrap { overflow-x: auto; }
.ag-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.ag-table th { text-align: left; color: var(--ag-muted); font-weight: 500; white-space: nowrap; padding: 8px 10px; border-bottom: 1px solid var(--ag-line); }
.ag-table td { padding: 8px 10px; border-bottom: 1px solid var(--ag-line-2); vertical-align: top; overflow-wrap: anywhere; }
.ag-table code, .ag-list code { font-family: var(--ag-mono); font-size: 12.5px; color: #4338ca; }
.ag-list { margin: 6px 0 0; padding-left: 18px; color: var(--ag-muted); font-size: 14px; }
.ag-list li { margin: 4px 0; overflow-wrap: anywhere; }
.ag-link { color: var(--ag-accent-strong); }
.ag-hosted-note { color: var(--ag-soft); font-size: 13px; line-height: 1.5; margin: 12px 0 0; }
@media (max-width: 640px) { .ag-page { padding: 10px 14px 32px; } .ag-switch button { padding: 7px 10px; font-size: 14px; } }
</style>
"""

SCRIPT = """
<script>
(() => {
  const tabs = [...document.querySelectorAll("[data-tab]")];
  const panels = [...document.querySelectorAll(".ag-scenario")];
  function show(name, update) {
    if (!panels.some((p) => p.dataset.scenario === name)) name = "passrole";
    panels.forEach((p) => { p.hidden = p.dataset.scenario !== name; });
    tabs.forEach((t) => {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    });
    if (update) {
      const url = new URL(location.href);
      if (name === "passrole") url.searchParams.delete("scenario"); else url.searchParams.set("scenario", name);
      history.replaceState(null, "", url);
    }
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => show(tab.dataset.tab, true));
    tab.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      show(next.dataset.tab, true);
    });
  });
  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-action]");
    if (!button) return;
    button.closest(".ag-scenario").dataset.simulated = button.dataset.action === "simulate" ? "true" : "false";
  });
  show(new URLSearchParams(location.search).get("scenario") || "passrole", false);
})();
</script>
"""

FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' "
    "rx='7' fill='%2353db78'/%3E%3Cpath d='M9 10h9a4 4 0 0 1 0 8h-4a4 4 0 0 0 0 8h9' fill='none' stroke='%23032b0c' "
    "stroke-width='3' stroke-linecap='round'/%3E%3C/svg%3E"
)

STATE_BADGE = {"true": ("green", "true"), "false": ("gray", "false"), "unknown": ("amber", "unknown")}
RESULT_BADGE = {"pass": ("green", "pass"), "fail": ("red", "fail"), "inconclusive": ("amber", "inconclusive")}


def badge(tone: str, text: str) -> str:
    return f'<span class="ag-badge {tone}">{esc(text)}</span>'


def load_recorded(path: Path, comparison) -> dict | None:
    """The recorded reply, only if it belongs to exactly this analysis and finding."""
    return landing.load_recorded(comparison, path)


def details(glyph: str, title: str, body: str) -> str:
    return f'<details class="ag-gloss"><summary>{web.icon(glyph)}{esc(title)}</summary>{body}</details>'


def ai_card(result, delta, story, recorded: dict | None) -> str:
    comparison = result.comparison
    packet = build_packet(comparison, delta, result.fixes)
    fix = next((f for f in result.fixes if f.removes(delta.id)), None)
    plain = " ".join(summary(story, fix))
    if recorded:
        text = (
            badge("green", "Recorded AI explanation")
            + f'<p class="ag-summary">{esc(recorded["summary"])}</p>'
            f'<p class="ag-note"><strong>Limitations:</strong> {esc(recorded["limitations"])}</p>'
        )
        side = (
            web.meta_list(
                [
                    ("Model", recorded["model_id"]),
                    ("Region", recorded["region"]),
                    ("Request", recorded["request_id"]),
                    ("Tokens", f"{recorded['input_tokens']:,} in, {recorded['output_tokens']:,} out"),
                    ("Latency", f"{recorded['latency_ms'] / 1000:.1f} s"),
                    ("Recorded", recorded["created_at"]),
                    ("Prompt", recorded["prompt_version"]),
                ]
            )
            + '<p class="ag-hosted-note">This hosted page never calls Bedrock. The reply was recorded from a live call and '
            "checked claim by claim; run the app locally to generate a new one.</p>"
            + details("rule", "Deterministic summary for comparison", f"<p>{esc(plain)}</p>")
        )
    else:
        text = badge("gray", "Deterministic summary, not AI-generated") + f'<p class="ag-summary">{esc(plain)}</p>'
        side = (
            '<p class="ag-hosted-note" style="margin-top:0">Live Amazon Bedrock explanations run in the local app. The hosted '
            "page makes no AI calls.</p>"
        )
    side += details("data_object", "What the model sees", f'<pre class="ag-json">{esc(json.dumps(packet.payload, indent=1))}</pre>')
    return (
        page.ai_intro(recorded["model_id"] if recorded else DEFAULT_MODEL_ID)
        + f'<div class="ag-split lead"><div>{text}</div><div>{side}</div></div>'
    )


def fix_card(result, delta, story) -> str:
    comparison = result.comparison
    head = web.card_head("healing", "The fix")
    blocker = page.fix_blocker(result, delta)
    if blocker:
        return head + f'<p class="ag-note">{esc(blocker)}</p>'
    best = best_fix_for(result.fixes, delta.id)
    chosen = best or result.fixes[0]
    buttons = (
        '<div class="ag-actions">'
        f'<button type="button" class="ag-btn ag-btn-primary ag-sim-off" data-action="simulate">{web.icon("science")}Simulate the fix</button>'
        '<button type="button" class="ag-btn ag-btn-ghost ag-sim-on" data-action="reset">Reset simulation</button>'
        "</div>"
    )
    left = page.fix_intro(chosen, best, story) + buttons + f'<div class="ag-sim-on">{page.fix_result(comparison, delta, chosen)}</div>'
    before, after = page.expected_block(comparison), page.expected_block(comparison, chosen)
    right = f'<div><div class="ag-sim-off">{before}</div><div class="ag-sim-on">{after}</div></div>' if before else ""
    return head + f'<div class="ag-split"><div>{left}</div>{right}</div>'


def condition_rows(candidate, comparison) -> str:
    rows = []
    for p in candidate.prerequisites:
        evidence = f"<code>{esc(p.fact_id)}</code>" if p.fact_id else ("not declared" if p.origin == "missing" else "derived")
        change = comparison.fact_change(p.fact_id) if p.fact_id else None
        if change is not None:
            evidence += " " + badge("new", f"changed {change.before} to {change.after}")
        if p.assumption:
            evidence += " " + badge("gray", "scenario assumption")
        note = f" ({esc(p.note)})" if p.note and p.state != "true" else ""
        pointers = ", ".join(f"<code>{esc(ptr)}</code>" for ptr in p.pointers) or "-"
        tone, word = STATE_BADGE[p.state]
        rows.append(f"<tr><td>{badge(tone, word)}</td><td>{esc(p.text)}{note}</td><td>{evidence}</td><td>{pointers}</td></tr>")
    return "".join(rows)


def evidence(result, delta, key: str) -> str:
    comparison = result.comparison
    parts = []
    if delta is not None:
        record = delta.current
        witness = record.witness if isinstance(record, Finding) else record.possible_witness
        parts.append("<h4>Every condition and its JSON pointer</h4>")
        for i, candidate in enumerate(witness, start=1):
            parts.append(
                f'<p class="ag-note">Step {i}. {esc(step_text(candidate))}: candidate <code>{esc(candidate.id)}</code> is '
                f"<strong>{esc(candidate.state)}</strong></p>"
                '<div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>State</th><th>Condition</th><th>Evidence</th>'
                f"<th>JSON pointer</th></tr></thead><tbody>{condition_rows(candidate, comparison)}</tbody></table></div>"
            )
        if isinstance(record, Finding):
            parts.append('<ul class="ag-list">' + "".join(f"<li>{esc(a)}</li>" for a in record.assumptions) + "</ul>")

    parts.append("<h4>Coverage</h4>")
    rows = []
    for label, analysis in (("Baseline", comparison.baseline), ("Proposed", comparison.proposal)):
        cov = analysis.coverage
        rules = [
            f"{c['true']} established, {c['false']} blocked, {c['unknown']} unresolved"
            for c in (cov.candidate_counts["s3_direct_read"], cov.candidate_counts["lambda_pass_role"])
        ]
        unresolved = [POLICY_CONTROLS[k].lower() for k, v in analysis.snapshot.policy_controls.items() if v != "resolved"]
        mechanisms = ", ".join(UNMODELLED_MECHANISMS[m] for m in analysis.snapshot.unmodelled_mechanisms) or "none"
        rows.append(
            f"<tr><td>{label}</td><td>{badge('green', 'complete') if cov.complete else badge('amber', 'incomplete')}</td>"
            f"<td>{esc(rules[0])}</td><td>{esc(rules[1])}</td>"
            f"<td>{esc('all 5 resolved' if not unresolved else 'unresolved: ' + ', '.join(unresolved))}</td><td>{esc(mechanisms)}</td></tr>"
        )
    parts.append(
        '<div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>Snapshot</th><th>Coverage</th><th>Rule A: direct S3 read</th>'
        "<th>Rule B: role use via Lambda</th><th>Policy controls</th><th>Unmodelled mechanisms</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )
    issues = [i for a in (comparison.baseline, comparison.proposal) for i in a.coverage.issues]
    if issues:
        parts.append('<ul class="ag-list">' + "".join(f"<li>{esc(i.message)}</li>" for i in issues[:30]) + "</ul>")

    parts.append("<h4>Every fact that changed</h4>")
    if comparison.fact_changes:
        rows = "".join(
            f"<tr><td><code>{esc(c.fact_id)}</code></td><td>{esc(c.describe())}</td><td>{esc(c.before)}</td>"
            f"<td>{esc(c.after)}</td><td><code>{esc((c.proposal or c.baseline).pointer)}</code></td></tr>"
            for c in comparison.fact_changes
        )
        parts.append(
            '<div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>Fact</th><th>Statement</th><th>Baseline</th>'
            f"<th>Proposed</th><th>Pointer</th></tr></thead><tbody>{rows}</tbody></table></div>"
        )
    else:
        parts.append('<p class="ag-note">No fact changed between the snapshots.</p>')

    parts.append(
        f'<h4>Full report</h4><p class="ag-note"><a class="ag-link" href="/reports/{esc(key)}.md" download>Download the Markdown '
        f"report</a> with every finding, pointer, coverage issue and assumption. Engine {esc(ENGINE_VERSION)}, model "
        f"{esc(MODEL_VERSION)}, analysis <code>{esc(comparison.analysis_id)}</code>.</p>"
    )
    return (
        f'<details class="ag-evidence"><summary>{web.icon("fact_check")}Evidence for reviewers: every condition, pointer and check'
        f'</summary><div class="ag-evidence-body">{"".join(parts)}</div></details>'
    )


def scenario_panel(key: str, result, recorded: dict | None) -> str:
    if not result.ok:
        body = page.invalid(result)
    else:
        comparison = result.comparison
        delta = comparison.deltas[0] if comparison.deltas else None
        body = page.verdict(result)
        if delta is None:
            body += page.stats(result) + evidence(result, None, key)
        else:
            story = build_story(comparison, delta)
            best = best_fix_for(result.fixes, delta.id)
            chosen = best or (result.fixes[0] if result.fixes else None)
            sim = chosen if chosen is not None and page.fix_blocker(result, delta) is None else None
            if sim:
                body += f'<div class="ag-sim-off">{page.stats(result)}</div><div class="ag-sim-on">{page.stats(result, sim)}</div>'
                path = (
                    f'<div class="ag-sim-off">{page.path_card(story)}</div>'
                    f'<div class="ag-sim-on">{page.path_card(story, sim)}</div>'
                )
            else:
                body += page.stats(result)
                path = page.path_card(story)
            cards = (
                path,
                page.change_card(comparison, story),
                page.conditions_card(story),
                ai_card(result, delta, story, recorded if key == "passrole" else None),
                fix_card(result, delta, story),
            )
            body += "".join(f'<div class="ag-scard">{card}</div>' for card in cards) + evidence(result, delta, key)
    hidden = "" if key == "passrole" else " hidden"
    return (
        f'<section class="ag-scenario" id="sc-{esc(key)}" role="tabpanel" aria-labelledby="tab-{esc(key)}" '
        f'data-scenario="{esc(key)}"{hidden}>{body}</section>'
    )


def upload_panel() -> str:
    return (
        f'<section class="ag-scenario" id="sc-{UPLOAD}" role="tabpanel" aria-labelledby="tab-{UPLOAD}" data-scenario="{UPLOAD}" hidden>'
        + web.verdict(
            "info",
            "Uploads run in the local app",
            "This hosted page is a static build of the bundled scenarios, so nothing you choose leaves your machine and no AI "
            "call is made. To analyse your own snapshots, run the app locally from the repository:",
        )
        + '<pre class="ag-json flat">python3 -m venv .venv &amp;&amp; .venv/bin/pip install -r requirements.txt\n'
        ".venv/bin/streamlit run app.py</pre>"
        '<p class="ag-note">Snapshots follow <code>attackgraph/snapshot.schema.json</code>; start from '
        "<code>fixtures/demo/</code>.</p></section>"
    )


HEAD = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>{title}</title>\n"
    '<meta name="description" content="AttackGraph AI finds new routes to admin roles and sensitive data in a proposed '
    'cloud change, explains them with Amazon Bedrock, and proves the fix.">\n'
    '<meta name="theme-color" content="#f9f9fa">\n'
    f'<link rel="icon" href="{FAVICON}">\n'
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700'
    '&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap">\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0,0'
    '&amp;display=block">\n'
)


def document(title: str, body: str, script: str = "") -> str:
    return (
        HEAD.replace("{title}", esc(title))
        + f"{web.CSS}{landing.CSS}{SITE_CSS}</head>\n<body>\n<main class=\"ag-page\">{body}</main>\n{script}</body>\n</html>\n"
    )


def build(out: Path, recorded_path: Path = RECORDED) -> Path:
    results = {key: run_scenario(key) for key in SCENARIOS}
    flagship = results["passrole"].comparison
    recorded = load_recorded(recorded_path, flagship)
    tabs = "".join(
        f'<button type="button" role="tab" id="tab-{esc(key)}" aria-controls="sc-{esc(key)}" data-tab="{esc(key)}" '
        f'aria-selected="{"true" if key == "passrole" else "false"}" tabindex="{0 if key == "passrole" else -1}">{esc(label)}</button>'
        for key, label in SCENARIO_LABELS.items()
    )
    panels = "".join(scenario_panel(key, results[key], recorded) for key in SCENARIOS) + upload_panel()
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = (
        f'<p class="ag-hosted-note">Static build of the bundled scenarios, generated {built} (UTC) by engine '
        f"{esc(ENGINE_VERSION)}. No uploads, no AI calls, no tracking.</p>"
    )
    landing_body = landing.page(results["passrole"], hosted=True, recorded_path=recorded_path).replace("</footer>", note + "</footer>")
    demo_body = (
        web.nav(web.DEMO)
        + landing.demo_header()
        + f'<div class="ag-switch" role="tablist" aria-label="Scenario">{tabs}</div>'
        + panels
        + landing.footer(hosted=True).replace("</footer>", note + "</footer>")
    )

    # Replace only what this script generates; keep dotfiles such as the Vercel project link.
    for generated in ("index.html", "vercel.json", "demo", "reports"):
        target = out / generated
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    (out / "reports").mkdir(parents=True)
    (out / "demo").mkdir()
    (out / "index.html").write_text(document("AttackGraph AI: ship permission changes without shipping admin access", landing_body))
    (out / "demo" / "index.html").write_text(document("Live demo: AttackGraph AI", demo_body, SCRIPT))
    for key, result in results.items():
        if result.ok:
            (out / "reports" / f"{key}.md").write_text(build_report(result.comparison, result.fixes))
    (out / "vercel.json").write_text(
        json.dumps(
            {
                "cleanUrls": True,
                "trailingSlash": False,
                "headers": [
                    {
                        "source": "/(.*)",
                        "headers": [
                            {"key": "X-Content-Type-Options", "value": "nosniff"},
                            {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"},
                            {"key": "X-Frame-Options", "value": "DENY"},
                            {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"},
                        ],
                    },
                    {"source": "/reports/(.*)", "headers": [{"key": "Content-Type", "value": "text/markdown; charset=utf-8"}]},
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return out / "index.html"


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site"
    index = build(target)
    demo = target / "demo" / "index.html"
    print(
        f"Wrote {index} ({index.stat().st_size:,} bytes), {demo} ({demo.stat().st_size:,} bytes) "
        f"and {len(list((target / 'reports').glob('*.md')))} reports"
    )
