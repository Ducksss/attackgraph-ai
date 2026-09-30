"""CSS and HTML fragments shared by every page, styled after the Close CRM template.

Streamlit sanitises st.html with DOMPurify and runs no JavaScript; the static
build is plain HTML. Every dynamic string still goes through esc(): labels
and messages come from uploaded files.
"""

from __future__ import annotations

import difflib
import html
import re

from .story import KIND_NAMES, Condition, PathNode, Story

ICONS = {"principal": "person", "role": "badge", "lambda": "deployed_code", "s3_object": "description"}
PROTECTED_ICONS = {"privileged_role": "admin_panel_settings", "sensitive_object": "lock"}
STATE_ICONS = {"true": "check_circle", "false": "cancel", "unknown": "help"}
RESULT_ICONS = {"pass": "check_circle", "fail": "cancel", "inconclusive": "help"}
LANDING, DEMO = "/", "/demo"

Segments = tuple[tuple[str, str], ...]  # ("text" | "node" | "id", value), as the explanation parser returns them


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def icon(name: str, extra: str = "") -> str:
    return f'<span class="ag-icon {extra}" aria-hidden="true">{esc(name)}</span>'


CSS = """
<style>
:root {
  --ag-bg: #f9f9fa;
  --ag-surface: #ffffff;
  --ag-surface-2: #f4f4f6;
  --ag-line: #e2e2e8;
  --ag-line-2: #ececf1;
  --ag-text: #111114;
  --ag-body: #3a3a44;
  --ag-muted: #5f5f72;
  --ag-soft: #9999a8;
  --ag-accent: #6366f1;
  --ag-accent-strong: #4044f0;
  --ag-accent-soft: #eef0ff;
  --ag-accent-line: #c7cafd;
  --ag-amber: #d97706;
  --ag-amber-text: #b45309;
  --ag-amber-soft: #fffbeb;
  --ag-amber-line: #fcd34d;
  --ag-red: #dc2626;
  --ag-red-text: #b91c1c;
  --ag-red-soft: #fef2f2;
  --ag-red-line: #fca5a5;
  --ag-green: #16a34a;
  --ag-green-text: #15803d;
  --ag-green-soft: #f0fdf4;
  --ag-green-line: #86efac;
  --ag-shadow: 0 2px 6px rgba(16, 24, 40, 0.06);
  --ag-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { max-width: 1200px; padding-top: 1rem; padding-bottom: 4rem; }
[data-testid="stHeaderActionElements"] { display: none; }
[data-testid="stMarkdownContainer"] code { overflow-wrap: anywhere; white-space: pre-wrap; }
[data-testid="stMarkdownContainer"] table { width: 100%; }
[data-testid="stMarkdownContainer"] th { white-space: nowrap; vertical-align: bottom; }
[data-testid="stMarkdownContainer"] td { overflow-wrap: break-word; vertical-align: top; }

.ag-icon {
  font-family: "Material Symbols Rounded"; font-weight: normal; font-style: normal; font-size: 20px;
  line-height: 1; letter-spacing: normal; text-transform: none; display: inline-block; white-space: nowrap;
  direction: ltr; -webkit-font-smoothing: antialiased; font-feature-settings: "liga"; vertical-align: middle;
}

.ag-nav { display: flex; align-items: center; justify-content: space-between; gap: 16px; background: var(--ag-surface);
  border: 1px solid var(--ag-line); border-radius: 12px; padding: 10px 12px 10px 16px; box-shadow: var(--ag-shadow); margin: 6px 0 8px; }
.ag-brand { display: flex; align-items: center; gap: 10px; color: var(--ag-text) !important; text-decoration: none !important;
  font-weight: 600; font-size: 17px; letter-spacing: -0.01em; }
.ag-logo { width: 30px; height: 30px; border-radius: 8px; background: var(--ag-accent); color: #fff; display: grid; place-items: center; }
.ag-logo .ag-icon { font-size: 20px; }
.ag-links { display: flex; gap: 4px; }
.ag-links a { color: var(--ag-body) !important; text-decoration: none !important; padding: 7px 12px; border-radius: 8px; font-size: 15px; }
.ag-links a:hover { background: var(--ag-surface-2); }
.ag-links a[aria-current="page"] { color: var(--ag-text) !important; font-weight: 500; background: var(--ag-surface-2); }

.ag-btn { display: inline-flex; align-items: center; gap: 8px; padding: 11px 18px; border-radius: 8px; font-weight: 500;
  font-size: 15px; line-height: 22px; text-decoration: none !important; white-space: nowrap; border: 1px solid transparent;
  transition: background-color 0.15s ease, border-color 0.15s ease, transform 0.1s ease; }
.ag-btn .ag-icon { font-size: 19px; }
.ag-btn-primary { background: var(--ag-accent); border-color: var(--ag-accent-strong); color: #fff !important; }
.ag-btn-primary:hover { background: #5458ee; }
.ag-btn-dark { background: #1d1d20; border-color: #1d1d20; color: #fff !important;
  box-shadow: inset 0 -3px 3.9px rgba(255, 255, 255, 0.12), inset 0 4px 6px rgba(0, 0, 0, 0.18); }
.ag-btn-dark:hover { background: #2b2b30; }
.ag-btn-ghost { background: var(--ag-surface); border-color: var(--ag-line); color: var(--ag-text) !important; box-shadow: var(--ag-shadow); }
.ag-btn-ghost:hover { border-color: #cfcfd8; }
.ag-btn:active { transform: translateY(1px); }
.ag-btn:focus-visible, .ag-links a:focus-visible, .ag-brand:focus-visible, .ag-faq summary:focus-visible,
.ag-gloss summary:focus-visible, .ag-evidence > summary:focus-visible { outline: 2px solid var(--ag-accent); outline-offset: 2px; }

.ag-pill { display: inline-flex; align-items: center; gap: 8px; padding: 5px 12px 5px 8px; border: 1px solid var(--ag-line);
  border-radius: 999px; font-size: 14px; color: var(--ag-body); background: var(--ag-surface); box-shadow: var(--ag-shadow); }
.ag-pill .ag-icon { color: var(--ag-accent); font-size: 18px; }
.ag-tag { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border: 1px solid var(--ag-line); border-radius: 999px;
  color: var(--ag-muted); font-size: 13px; font-weight: 500; background: var(--ag-surface); }
.ag-tag .ag-icon { font-size: 16px; color: var(--ag-accent); }
.ag-h1 { font-size: clamp(36px, 4.6vw, 60px); line-height: 1.1; font-weight: 500; letter-spacing: -0.03em; margin: 18px 0 14px;
  padding: 0; color: var(--ag-text); }
.ag-h2 { font-size: clamp(30px, 3.6vw, 48px); line-height: 1.2; font-weight: 500; letter-spacing: -0.035em; margin: 12px 0 12px;
  padding: 0; color: var(--ag-text); }
.ag-h1 .ag-soft, .ag-h2 .ag-soft { color: var(--ag-soft); }
.ag-h2 .ag-soft, .ag-h1 .ag-soft.line { display: block; }
.ag-lead { font-size: 19px; line-height: 30px; color: var(--ag-muted); max-width: 640px; margin: 0 auto; }
.ag-sub { color: var(--ag-muted); font-size: 17px; line-height: 27px; max-width: 680px; margin: 0; }
.ag-center { text-align: center; }
.ag-center .ag-sub, .ag-center .ag-lead { margin: 0 auto; }
.ag-cta { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-top: 26px; }
.ag-section { margin: 88px 0 28px; scroll-margin-top: 24px; }
.ag-hatch { height: 44px; margin: 72px 0 0; border-top: 1px solid var(--ag-line); border-bottom: 1px solid var(--ag-line);
  background: repeating-linear-gradient(135deg, transparent 0 7px, #e7e7ed 7px 8px); }

.ag-card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; flex-wrap: wrap; }
.ag-card-head .ag-icon { color: var(--ag-accent); font-size: 22px; }
.ag-card-title { font-size: 21px; font-weight: 500; letter-spacing: -0.01em; margin: 0; padding: 0; color: var(--ag-text); }
.ag-note { color: var(--ag-muted); font-size: 15px; line-height: 1.6; margin: 6px 0 0; }
.ag-small { color: var(--ag-soft); font-size: 13px; }
.ag-mono { font-family: var(--ag-mono); font-size: 12.5px; color: #4338ca; overflow-wrap: anywhere; }
.ag-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; border-radius: 999px; padding: 2px 9px;
  border: 1px solid; white-space: nowrap; }
.ag-badge.new { color: #92400e; background: #fef3c7; border-color: var(--ag-amber-line); }
.ag-badge.green { color: #166534; background: #dcfce7; border-color: var(--ag-green-line); }
.ag-badge.amber { color: var(--ag-amber-text); background: var(--ag-amber-soft); border-color: var(--ag-amber-line); }
.ag-badge.red { color: var(--ag-red-text); background: var(--ag-red-soft); border-color: var(--ag-red-line); }
.ag-badge.gray { color: var(--ag-muted); background: var(--ag-surface-2); border-color: var(--ag-line); }
.ag-badge.indigo { color: #4338ca; background: var(--ag-accent-soft); border-color: var(--ag-accent-line); }

.ag-verdict { display: flex; gap: 14px; align-items: flex-start; border: 1px solid; border-radius: 12px; padding: 18px 22px; margin: 8px 0 16px;
  background: var(--ag-surface); }
.ag-verdict .ag-icon { font-size: 28px; margin-top: 2px; }
.ag-verdict h3 { margin: 0; padding: 0; font-size: 22px; line-height: 1.3; font-weight: 500; letter-spacing: -0.01em; color: var(--ag-text); }
.ag-verdict p { margin: 4px 0 0; color: var(--ag-muted); font-size: 15px; line-height: 1.55; }
.ag-verdict.risk { border-color: var(--ag-amber-line); background: var(--ag-amber-soft); }
.ag-verdict.risk .ag-icon, .ag-verdict.unknown .ag-icon { color: var(--ag-amber); }
.ag-verdict.unknown { border-color: var(--ag-amber-line); background: #fffdf5; }
.ag-verdict.safe { border-color: var(--ag-green-line); background: var(--ag-green-soft); }
.ag-verdict.safe .ag-icon { color: var(--ag-green); }
.ag-verdict.error { border-color: var(--ag-red-line); background: var(--ag-red-soft); }
.ag-verdict.error .ag-icon { color: var(--ag-red); }
.ag-verdict.info { border-color: var(--ag-line); }
.ag-verdict.info .ag-icon { color: var(--ag-accent); }
.ag-errors { margin: 10px 0 0; padding-left: 18px; color: var(--ag-body); }
.ag-errors li { margin: 4px 0; overflow-wrap: anywhere; }
.ag-errors code { font-family: var(--ag-mono); color: var(--ag-red-text); font-size: 12.5px; }

.ag-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 8px; }
.ag-stats.two { grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 16px 0 4px; }
.ag-stat { border: 1px solid var(--ag-line); border-radius: 12px; padding: 16px 18px; background: var(--ag-surface); }
.ag-stat-label { color: var(--ag-muted); font-size: 14px; }
.ag-stat-value { font-size: clamp(18px, 5.6vw, 28px); line-height: 1.25; font-weight: 500; letter-spacing: -0.02em; margin-top: 4px;
  font-variant-numeric: tabular-nums; color: var(--ag-text); }
.ag-stat-note { color: var(--ag-soft); font-size: 13px; margin-top: 4px; overflow-wrap: anywhere; }
.ag-stat.risk .ag-stat-value { color: var(--ag-amber-text); }
.ag-stat.good .ag-stat-value { color: var(--ag-green-text); }

.ag-change { border: 1px solid var(--ag-amber-line); background: var(--ag-amber-soft); border-radius: 10px; padding: 14px 16px; margin-top: 14px; }
.ag-change-text { font-size: 16px; line-height: 1.5; color: var(--ag-text); font-weight: 500; }
.ag-flip { display: inline-flex; align-items: center; gap: 6px; margin-top: 8px; font-family: var(--ag-mono); font-size: 13px; }
.ag-flip .from { color: var(--ag-soft); text-decoration: line-through; }
.ag-flip .to { color: var(--ag-amber-text); font-weight: 600; }
.ag-gloss { margin-top: 14px; border: 1px solid var(--ag-line); border-radius: 10px; background: var(--ag-surface); }
.ag-gloss summary { cursor: pointer; padding: 10px 14px; color: var(--ag-text); font-size: 15px; list-style: none; display: flex; align-items: center; gap: 8px; }
.ag-gloss summary::-webkit-details-marker { display: none; }
.ag-gloss summary .ag-icon { color: var(--ag-accent); font-size: 18px; }
.ag-gloss p { margin: 0; padding: 0 14px 12px; color: var(--ag-muted); font-size: 15px; line-height: 1.6; }

.ag-path { display: flex; align-items: stretch; flex-wrap: wrap; row-gap: 14px; margin: 16px 0 6px; }
.ag-node { flex: 1 1 120px; min-width: 112px; max-width: 240px; border: 1px solid var(--ag-line); border-radius: 10px; padding: 12px 14px;
  background: var(--ag-surface); box-sizing: border-box; box-shadow: var(--ag-shadow); }
.ag-node-kind { display: flex; align-items: center; gap: 6px; color: var(--ag-muted); font-size: 12px; }
.ag-node-kind .ag-icon { font-size: 18px; color: var(--ag-accent); }
.ag-node-label { font-size: 15px; line-height: 1.35; font-weight: 500; margin-top: 6px; color: var(--ag-text); overflow-wrap: anywhere; }
.ag-node-id { font-family: var(--ag-mono); font-size: 11.5px; color: var(--ag-soft); margin-top: 4px; overflow-wrap: anywhere; }
.ag-node.protected { border-color: var(--ag-amber-line); box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.14), var(--ag-shadow); }
.ag-node.protected .ag-node-kind, .ag-node.protected .ag-node-kind .ag-icon { color: var(--ag-amber-text); }
.ag-node.faded, .ag-hop.faded { opacity: 0.4; }
.ag-hop { flex: 1 1 84px; min-width: 72px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: center;
  padding: 0 8px; text-align: center; }
.ag-hop-badge { align-self: center; margin-bottom: 6px; font-size: 11px; padding: 1px 8px; }
.ag-hop-text { font-size: 12.5px; line-height: 1.3; color: var(--ag-muted); margin-bottom: 7px; overflow-wrap: anywhere; }
.ag-hop-line { height: 2px; background: var(--ag-accent); position: relative; margin-right: 6px; }
.ag-hop-line::after { content: ""; position: absolute; right: -7px; top: -5px; border-left: 8px solid var(--ag-accent);
  border-top: 6px solid transparent; border-bottom: 6px solid transparent; }
.ag-hop.new .ag-hop-text { color: var(--ag-amber-text); font-weight: 600; }
.ag-hop.new .ag-hop-line { background: var(--ag-amber); }
.ag-hop.new .ag-hop-line::after { border-left-color: var(--ag-amber); }
.ag-hop.cut .ag-hop-text { color: var(--ag-red-text); font-weight: 600; }
.ag-hop.cut .ag-hop-line { background: repeating-linear-gradient(90deg, var(--ag-red) 0 6px, transparent 6px 11px); }
.ag-hop.cut .ag-hop-line::after { border-left-color: var(--ag-red); }
.ag-hop.maybe .ag-hop-line { background: repeating-linear-gradient(90deg, var(--ag-amber) 0 6px, transparent 6px 11px); }
.ag-hop.maybe .ag-hop-line::after { border-left-color: var(--ag-amber); }
@media (prefers-reduced-motion: no-preference) {
  .ag-hop.new .ag-hop-line { animation: ag-pulse 2.6s ease-in-out infinite; }
}
@keyframes ag-pulse { 0%, 100% { box-shadow: 0 0 0 rgba(245, 158, 11, 0); } 50% { box-shadow: 0 0 10px rgba(245, 158, 11, 0.8); } }
.ag-path.compact .ag-node { padding: 10px 12px; }
.ag-path.compact .ag-node-id { display: none; }

.ag-conds { list-style: none; padding: 0 !important; margin: 10px 0 0 !important; display: grid; gap: 8px; }
.ag-conds li { margin: 0 !important; }
.ag-cond { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--ag-line); border-radius: 10px;
  background: var(--ag-surface); }
.ag-cond > .ag-icon { font-size: 20px; margin-top: 1px; }
.ag-cond.true > .ag-icon { color: var(--ag-green); }
.ag-cond.false > .ag-icon { color: var(--ag-red); }
.ag-cond.unknown > .ag-icon { color: var(--ag-amber); }
.ag-cond.changed { border-color: var(--ag-amber-line); background: var(--ag-amber-soft); }
.ag-cond-text { color: var(--ag-text); font-size: 15px; line-height: 1.45; overflow-wrap: anywhere; }
.ag-cond-meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 4px; }
.ag-step-title { font-size: 15px; font-weight: 600; margin: 18px 0 2px; color: var(--ag-text); }
.ag-summary { color: var(--ag-body); font-size: 16px; line-height: 1.65; margin: 8px 0 0; }
.ag-ent { display: inline-block; max-width: 100%; padding: 0 5px 0 4px; border-radius: 5px; background: var(--ag-accent-soft);
  color: var(--ag-text); font-weight: 500; line-height: 1.45; overflow-wrap: anywhere; }
.ag-ent .ag-icon { font-size: 14px; color: var(--ag-accent); margin-right: 2px; vertical-align: -2px; }
.ag-ent.protected { background: var(--ag-amber-soft); }
.ag-ent.protected .ag-icon { color: var(--ag-amber-text); }
.ag-badges { display: flex; flex-wrap: wrap; gap: 6px; }
.ag-fix-result { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--ag-line-2); }

.ag-inside { margin: 36px 0 4px; }
.ag-inside .ag-note { margin-top: 8px; }
.ag-pr { border: 1px solid var(--ag-line); border-radius: 12px; overflow: hidden; margin-top: 14px; background: var(--ag-surface); }
.ag-pr-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 4px 16px; padding: 12px 16px;
  background: var(--ag-surface-2); border-bottom: 1px solid var(--ag-line); }
.ag-pr-title { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; color: var(--ag-text); }
.ag-pr-title .ag-icon { color: var(--ag-accent); font-size: 20px; }
.ag-pr-meta { color: var(--ag-muted); font-size: 13px; }
.ag-diff-file { padding: 8px 16px; font-family: var(--ag-mono); font-size: 12.5px; color: var(--ag-body); border-bottom: 1px solid var(--ag-line-2); }
.ag-diff { font-family: var(--ag-mono); font-size: 12.5px; line-height: 1.6; padding: 4px 0; }
.ag-dl { display: grid; grid-template-columns: 48px 20px minmax(0, 1fr); color: var(--ag-body); }
.ag-dl .n { text-align: right; padding-right: 10px; color: var(--ag-soft); user-select: none; }
.ag-dl .s { color: var(--ag-soft); user-select: none; }
.ag-dl code { font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; padding: 0 16px 0 0; background: none; color: inherit; }
.ag-dl.del { background: #fff5f5; }
.ag-dl.del .s { color: var(--ag-red); }
.ag-dl.add { background: #f0fdf4; }
.ag-dl.add .s { color: var(--ag-green); }
.ag-dl mark { color: inherit; border-radius: 3px; padding: 0 1px; }
.ag-dl.del mark { background: #fecaca; }
.ag-dl.add mark { background: #bbf7d0; }
.ag-annot { margin: 6px 16px 10px 68px; padding: 10px 14px; border: 1px solid var(--ag-red-line); border-left: 4px solid var(--ag-red);
  border-radius: 8px; background: var(--ag-surface); font-family: "Inter", system-ui, -apple-system, sans-serif; }
.ag-annot-title { display: flex; align-items: flex-start; gap: 6px; font-weight: 600; font-size: 14px; line-height: 1.45; color: var(--ag-red-text); }
.ag-annot-title .ag-icon { font-size: 18px; flex: none; margin-top: 1px; }
.ag-annot-src { font-weight: 400; color: var(--ag-soft); font-size: 12.5px; margin-left: 4px; }
.ag-annot p { margin: 4px 0 0; color: var(--ag-body); font-size: 14px; line-height: 1.55; }
.ag-annot.notice { border-color: var(--ag-accent-line); border-left-color: var(--ag-accent); }
.ag-annot.notice .ag-annot-title { color: var(--ag-accent-strong); }
.ag-annot.warning { border-color: var(--ag-amber-line); border-left-color: var(--ag-amber); }
.ag-annot.warning .ag-annot-title { color: var(--ag-amber-text); }
.ag-pr-check { display: flex; gap: 10px; align-items: flex-start; padding: 12px 16px; border-top: 1px solid var(--ag-line); background: var(--ag-surface-2); }
.ag-pr-check > .ag-icon { font-size: 22px; margin-top: 1px; }
.ag-pr-check.fail > .ag-icon { color: var(--ag-red); }
.ag-pr-check.pass > .ag-icon { color: var(--ag-green); }
.ag-pr-check .ag-note { margin: 2px 0 0; }
.ag-log { margin-top: 6px; }
.ag-log summary { cursor: pointer; color: var(--ag-accent-strong); font-size: 13.5px; width: fit-content; }
.ag-log summary:focus-visible { outline: 2px solid var(--ag-accent); outline-offset: 2px; }
.ag-log pre { margin: 8px 0 0; padding: 10px 12px; border: 1px solid var(--ag-line); border-radius: 8px; background: var(--ag-surface);
  font-family: var(--ag-mono); font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ag-body); }
.ag-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 28px; align-items: start; margin-top: 14px; }
.ag-split.lead { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); }
.ag-split > :only-child { grid-column: 1 / -1; }
.ag-split .ag-change:first-child, .ag-split > div > .ag-note:first-child { margin-top: 0; }
.ag-gloss-box { border: 1px solid var(--ag-line); border-radius: 10px; background: var(--ag-surface-2); padding: 14px 16px; }
.ag-gloss-title { display: flex; align-items: center; gap: 8px; font-weight: 500; color: var(--ag-text); font-size: 15px; }
.ag-gloss-title .ag-icon { color: var(--ag-accent); font-size: 18px; }
.ag-gloss-box p { margin: 6px 0 0; color: var(--ag-muted); font-size: 15px; line-height: 1.6; }
.ag-conds.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.ag-key { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 14px; color: var(--ag-soft); font-size: 13px; }
.ag-key > span { display: inline-flex; align-items: center; gap: 6px; }
.ag-key-line { display: inline-block; width: 22px; border-top: 2px solid var(--ag-accent); }
.ag-key-line.new { border-top-color: var(--ag-amber); }
.ag-key-line.maybe { border-top-style: dashed; border-top-color: var(--ag-amber); }
.ag-key-line.cut { border-top-style: dashed; border-top-color: var(--ag-red); }
.ag-key-line.faded { opacity: 0.4; }
.ag-meta { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 14px; margin: 0; font-size: 13.5px; line-height: 1.45; }
.ag-meta dt { color: var(--ag-soft); }
.ag-meta dd { margin: 0; color: var(--ag-body); overflow-wrap: anywhere; }
.ag-label { color: var(--ag-text); font-size: 15px; font-weight: 500; margin: 0; }
.ag-expect { list-style: none; padding: 0 !important; margin: 10px 0 0 !important; display: grid; gap: 6px; }
.ag-expect li { margin: 0 !important; display: flex; gap: 8px; align-items: flex-start; color: var(--ag-text); font-size: 15px; line-height: 1.45; }
.ag-expect li .ag-icon { font-size: 19px; color: var(--ag-green); margin-top: 1px; }
.ag-expect li.fail .ag-icon { color: var(--ag-red); }
.ag-expect li.inconclusive .ag-icon { color: var(--ag-amber); }

[class*="st-key-agcard-"] { background: var(--ag-surface); border: 1px solid var(--ag-line); border-radius: 12px; padding: 22px 22px 18px;
  box-shadow: var(--ag-shadow); }
[data-testid="stBaseButton-primary"] { background: var(--ag-accent) !important; border: 1px solid var(--ag-accent-strong) !important; color: #fff !important; }
[data-testid="stBaseButton-primary"]:hover { background: #5458ee !important; }
[data-testid="stBaseButton-secondary"] { background: var(--ag-surface) !important; border: 1px solid var(--ag-line) !important;
  color: var(--ag-text) !important; box-shadow: var(--ag-shadow); }
[data-testid="stBaseButton-secondary"]:hover { border-color: #cfcfd8 !important; }
[data-testid="stExpander"] details { border-color: var(--ag-line) !important; background: var(--ag-surface); border-radius: 12px; }

.ag-chips { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }
.ag-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 1px solid var(--ag-line); border-radius: 999px;
  font-size: 14px; color: var(--ag-body); background: var(--ag-surface); }
.ag-chip .ag-icon { color: var(--ag-green); font-size: 18px; }
.ag-faq details { border: 1px solid var(--ag-line); border-radius: 12px; margin-bottom: 10px; background: var(--ag-surface); }
.ag-faq summary { cursor: pointer; list-style: none; padding: 16px 20px; font-weight: 500; font-size: 16px; color: var(--ag-text);
  display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.ag-faq summary::-webkit-details-marker { display: none; }
.ag-faq summary::after { content: "add"; font-family: "Material Symbols Rounded"; font-size: 22px; color: var(--ag-soft); font-feature-settings: "liga"; }
.ag-faq details[open] summary::after { content: "remove"; }
.ag-faq details p { margin: 0; padding: 0 20px 18px; color: var(--ag-muted); font-size: 15px; line-height: 1.65; }

@media (max-width: 900px) {
  .ag-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ag-links { display: none; }
  .ag-split, .ag-split.lead, .ag-conds.two { grid-template-columns: minmax(0, 1fr); gap: 16px; }
}
@media (max-width: 640px) {
  .ag-dl { grid-template-columns: 34px 14px minmax(0, 1fr); }
  .ag-dl .n { padding-right: 6px; }
  .ag-annot { margin-left: 12px; margin-right: 12px; }
  .ag-nav { padding: 8px 8px 8px 12px; }
  .ag-brand { font-size: 15px; }
  .ag-nav .ag-btn { padding: 8px 12px; font-size: 14px; }
  .ag-path { flex-direction: column; flex-wrap: nowrap; }
  .ag-node { max-width: none; flex: none; }
  .ag-hop { flex: none; flex-direction: row; align-items: center; justify-content: flex-start; gap: 12px; padding: 4px 0 4px 20px;
    text-align: left; min-height: 48px; }
  .ag-hop-text { margin: 0; order: 3; }
  .ag-hop-badge { order: 2; margin: 0; }
  .ag-hop-line { width: 2px; height: 34px; margin: 0 0 8px; order: 1; flex: none; }
  .ag-hop-line::after { right: -5px; top: auto; bottom: -8px; border-left: 6px solid transparent; border-right: 6px solid transparent;
    border-top: 8px solid var(--ag-accent); border-bottom: 0; }
  .ag-hop.new .ag-hop-line::after, .ag-hop.maybe .ag-hop-line::after { border-left-color: transparent; border-top-color: var(--ag-amber); }
  .ag-hop.cut .ag-hop-line::after { border-left-color: transparent; border-top-color: var(--ag-red); }
  .ag-hop.cut .ag-hop-line { background: repeating-linear-gradient(180deg, var(--ag-red) 0 6px, transparent 6px 11px); }
  .ag-hop.maybe .ag-hop-line { background: repeating-linear-gradient(180deg, var(--ag-amber) 0 6px, transparent 6px 11px); }
}
@media (max-width: 360px) {
  .ag-nav .ag-btn-dark { display: none; }
}
</style>
"""


def nav(active: str) -> str:
    """Top bar shared by both pages; active is LANDING or DEMO."""
    home = "" if active == LANDING else LANDING
    links = (
        f'<a href="{home}#why">Why it matters</a><a href="{home}#how">How it works</a><a href="{home}#trust">Trust</a>'
        + (f'<a href="{DEMO}" aria-current="page">Live demo</a>' if active == DEMO else "")
    )
    cta = (
        f'<a class="ag-btn ag-btn-dark" href="{DEMO}">Open the live demo</a>'
        if active == LANDING
        else f'<a class="ag-btn ag-btn-ghost" href="{LANDING}">Back to overview</a>'
    )
    return (
        '<nav class="ag-nav" aria-label="Site">'
        f'<a class="ag-brand" href="{LANDING}"><span class="ag-logo">{icon("conversion_path")}</span>AttackGraph AI</a>'
        f'<div class="ag-links">{links}</div>{cta}</nav>'
    )


def section_head(title: str, soft: str = "", sub: str = "", tag: str = "", anchor: str = "", center: bool = True) -> str:
    """Two-tone headline in the Close style: title in black, soft continuation in grey."""
    tag_html = f'<span class="ag-tag">{esc(tag)}</span>' if tag else ""
    soft_html = f' <span class="ag-soft">{esc(soft)}</span>' if soft else ""
    return (
        f'<div class="ag-section{" ag-center" if center else ""}"' + (f' id="{esc(anchor)}"' if anchor else "") + ">"
        + tag_html
        + f'<h2 class="ag-h2">{esc(title)}{soft_html}</h2>'
        + (f'<p class="ag-sub">{esc(sub)}</p>' if sub else "")
        + "</div>"
    )


KEY_TEXT = {
    "": "Established relationship",
    "new": "New in the proposal",
    "maybe": "Depends on an unknown condition",
    "cut": "Revoked or removed",
    "faded": "No longer reachable",
}
CUT_TEXT = {"simulated": "Revoked by the simulated fix", "closed": "Removed in the second snapshot"}


def path(story: Story, mode: str = "live", compact: bool = False, key: bool = False, revoked: str | None = None) -> str:
    """The route as node cards joined by labelled arrows.

    mode "live" marks changed hops as new (as changed while the comparison is
    unresolved) and dashes unresolved ones, badging the hop whose own
    condition is unknown; "simulated" and "closed" mark the cut hop as revoked
    or removed and fade everything after it. revoked names the fact a
    simulated fix revokes, so only its hop is cut. key adds a legend for the
    line styles drawn.
    """
    unresolved = story.delta.status == "inconclusive"
    parts = []
    used = set()
    cut = False
    for i, node in enumerate(story.nodes):
        if i:
            hop = story.hops[i - 1]
            cls, tag = "", ""
            if cut:
                cls = "faded"
            elif mode == "simulated" and hop.changed and (revoked is None or revoked in hop.fact_ids):
                cls, tag, cut = "cut", ("red", "Revoked"), True
            elif mode == "closed" and hop.changed:
                cls, tag, cut = "cut", ("red", "Removed"), True
            elif hop.state == "unknown":
                cls, tag = "maybe", ("amber", "Unknown") if hop.unknown else ""
            elif hop.changed:
                cls, tag = "new", ("new", "Changed" if unresolved else "New")
            elif hop.state != "true":
                cls = "maybe"
            used.add(cls)
            badge = f'<span class="ag-badge {tag[0]} ag-hop-badge">{esc(tag[1])}</span>' if tag else ""
            parts.append(
                f'<div class="ag-hop {cls}">{badge}<div class="ag-hop-text">{esc(hop.text)}</div>'
                '<div class="ag-hop-line"></div></div>'
            )
        kind = KIND_NAMES[node.kind]
        glyph = ICONS[node.kind]
        classes = ["ag-node"]
        if node.protected:
            kind = "Protected " + ("role" if node.protected == "privileged_role" else "data")
            glyph = PROTECTED_ICONS[node.protected]
            classes.append("protected")
        if cut:
            classes.append("faded")
        parts.append(
            f'<div class="{" ".join(classes)}"><div class="ag-node-kind">{icon(glyph)}{esc(kind)}</div>'
            f'<div class="ag-node-label">{esc(node.label)}</div><div class="ag-node-id">{esc(node.id)}</div></div>'
        )
    label = "Route: " + " then ".join(esc(n.label) for n in story.nodes)
    out = f'<div class="ag-path{" compact" if compact else ""}" role="img" aria-label="{label}">' + "".join(parts) + "</div>"
    if key:
        text = dict(KEY_TEXT, cut=CUT_TEXT.get(mode, KEY_TEXT["cut"]))
        if unresolved:
            text["new"] = "Changed in the proposal"
        items = [f'<span><span class="ag-key-line {c}"></span>{esc(text[c])}</span>' for c in KEY_TEXT if c in used]
        out += '<div class="ag-key" aria-hidden="true">' + "".join(items) + "</div>"
    return out


def reply(segments: Segments, nodes: tuple[PathNode, ...]) -> str:
    """Model text with each entity placeholder shown by the name it stands for.

    Names are uploaded display text, so they are escaped and drawn as chips: a
    label can never pass for the model's own words. Facts, checks and fixes
    keep their IDs in monospace, as everywhere else on the page.
    """
    names = {node.id: node for node in nodes}
    out = []
    for kind, value in segments:
        node = names.get(value) if kind == "node" else None
        if node is not None:
            glyph = PROTECTED_ICONS[node.protected] if node.protected else ICONS[node.kind]
            cls = "ag-ent protected" if node.protected else "ag-ent"
            out.append(f'<span class="{cls}" title="{esc(node.id)}">{icon(glyph)}{esc(node.label)}</span>')
        elif kind == "text":
            out.append(esc(value))
        else:
            out.append(f'<span class="ag-mono">{esc(value)}</span>')
    return "".join(out)


_TOKENS = re.compile(r"\w+|\s+|[^\w\s]")


def _marked(text: str, other: str) -> str:
    """text with the words that differ from other marked, so a flipped value stands out in its line."""
    mine, theirs = _TOKENS.findall(text), _TOKENS.findall(other)
    out = []
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, mine, theirs, autojunk=False).get_opcodes():
        part = esc("".join(mine[i1:i2]))
        out.append(part if tag == "equal" or not part else f"<mark>{part}</mark>")
    return "".join(out)


def diff(before: str, after: str, notes: dict[int, str] | None = None, context: int = 1) -> str:
    """A unified diff of two texts, numbered by line, with changed words marked.

    notes maps a line number in the new text to HTML placed right under that
    line, the way a code review shows a check's annotation.
    """
    notes = notes or {}
    old, new = before.splitlines(), after.splitlines()

    def row(kind: str, number: int, sign: str, code: str) -> str:
        line = f'<div class="ag-dl {kind}"><span class="n">{number}</span><span class="s">{sign}</span><code>{code}</code></div>'
        return line + (notes.get(number, "") if kind != "del" else "")

    rows = []
    for group in difflib.SequenceMatcher(None, old, new, autojunk=False).get_grouped_opcodes(context):
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                rows += [row("ctx", j1 + k + 1, " ", esc(new[j1 + k])) for k in range(j2 - j1)]
                continue
            paired = tag == "replace" and i2 - i1 == j2 - j1
            rows += [
                row("del", i1 + k + 1, "-", _marked(old[i1 + k], new[j1 + k]) if paired else esc(old[i1 + k]))
                for k in range(i2 - i1)
            ]
            rows += [
                row("add", j1 + k + 1, "+", _marked(new[j1 + k], old[i1 + k]) if paired else esc(new[j1 + k]))
                for k in range(j2 - j1)
            ]
    return '<div class="ag-diff">' + "".join(rows) + "</div>"


def annotation(level: str, title: str, message: str, source: str) -> str:
    """A check's note on a line, as a code review shows it."""
    glyph = {"error": "cancel", "warning": "warning"}.get(level, "info")
    return (
        f'<div class="ag-annot {esc(level)}" role="note"><div class="ag-annot-title">{icon(glyph)}<span>{esc(title)}'
        f'<span class="ag-annot-src">{esc(source)}</span></span></div><p>{esc(message)}</p></div>'
    )


def condition_item(condition: Condition) -> str:
    classes = ["ag-cond", condition.state] + (["changed"] if condition.change else [])
    meta = []
    if condition.change:
        before, after = condition.change.split(" → ")
        meta.append(f'<span class="ag-badge new">Changed: {esc(before)} to {esc(after)}</span>')
    if condition.assumption:
        meta.append('<span class="ag-badge gray">Scenario assumption</span>')
    if condition.state == "unknown":
        meta.append('<span class="ag-badge amber">Unknown</span>')
    if condition.fact_id:
        meta.append(f'<span class="ag-mono">{esc(condition.fact_id)}</span>')
    return (
        f'<li class="{" ".join(classes)}">{icon(STATE_ICONS[condition.state])}<div>'
        f'<div class="ag-cond-text">{esc(condition.text)}</div>'
        + (f'<div class="ag-cond-meta">{"".join(meta)}</div>' if meta else "")
        + "</div></li>"
    )


def conditions(story: Story, two: bool = False) -> str:
    """One checklist per step; step titles only appear when the route has several steps."""
    out = []
    several = len(story.steps) > 1
    for step in story.steps:
        if several:
            held = sum(1 for c in step.conditions if c.state == "true")
            out.append(f'<div class="ag-step-title">{esc(step.title)}</div>')
            out.append(f'<div class="ag-small">{held} of {len(step.conditions)} conditions hold.</div>')
        out.append(f'<ul class="ag-conds{" two" if two else ""}">' + "".join(condition_item(c) for c in step.conditions) + "</ul>")
    return "".join(out)


def change_block(story: Story) -> str:
    if not story.changes:
        return '<p class="ag-note">No condition on this route changed between the snapshots.</p>'
    blocks = []
    for change in story.changes:
        before, after = change.change.split(" → ")
        pointer = f'<span class="ag-mono">{esc(change.pointers[0])}</span>' if change.pointers else ""
        if change.fact_id:
            where = f'Fact <span class="ag-mono">{esc(change.fact_id)}</span> at {pointer or "-"}'
        else:  # a derived check, such as the policy controls, or a fact one snapshot does not declare
            where = f"Declared at {pointer}" if pointer else "Not declared in this snapshot"
        blocks.append(
            f'<div class="ag-change"><div class="ag-change-text">{esc(change.text)}</div>'
            f'<div class="ag-flip"><span class="from">{esc(before)}</span>{icon("arrow_forward")}'
            f'<span class="to">{esc(after)}</span></div>'
            f'<div class="ag-small" style="margin-top:6px">{where}</div></div>'
        )
    return "".join(blocks)


PASSROLE_GLOSSARY = (
    '<div class="ag-gloss-box"><div class="ag-gloss-title">' + icon("school") + "What is iam:PassRole?</div>"
    "<p>It is the permission to hand an IAM role to an AWS service. If someone can hand a powerful role to a Lambda "
    "function they write and run, their code runs with that role's permissions. That is why this one permission "
    "matters.</p></div>"
)


def card_head(glyph: str, title: str, badge: str = "") -> str:
    return f'<div class="ag-card-head">{icon(glyph)}<h3 class="ag-card-title">{esc(title)}</h3>{badge}</div>'


def verdict(kind: str, title: str, body: str, errors: list[tuple[str, str]] | None = None) -> str:
    glyph = {"risk": "warning", "safe": "check_circle", "unknown": "help", "error": "error", "info": "upload_file"}[kind]
    items = ""
    if errors:
        items = '<ul class="ag-errors">' + "".join(
            f"<li><code>{esc(p or '(file)')}</code> {esc(m)}</li>" for p, m in errors
        ) + "</ul>"
    return (
        f'<div class="ag-verdict {kind}" role="status">{icon(glyph)}<div><h3>{esc(title)}</h3>'
        f"<p>{esc(body)}</p>{items}</div></div>"
    )


def stats(cards: list[tuple[str, str, str, str]], columns: int = 4) -> str:
    """cards: (label, value, note, tone) with tone in {"", "risk", "good"}."""
    return f'<div class="ag-stats{" two" if columns == 2 else ""}">' + "".join(
        f'<div class="ag-stat {esc(tone)}"><div class="ag-stat-label">{esc(label)}</div>'
        f'<div class="ag-stat-value">{esc(value)}</div><div class="ag-stat-note">{esc(note)}</div></div>'
        for label, value, note, tone in cards
    ) + "</div>"


def expected_list(rows: list[tuple[str, str, str | None]]) -> str:
    """rows: (text, proposed result, simulated result or None)."""
    items = []
    for text, proposed, simulated in rows:
        shown = simulated or proposed
        state = f"Proposed: {proposed}" + (f", after the fix: {simulated}" if simulated else "")
        items.append(
            f'<li class="{esc(shown)}">{icon(RESULT_ICONS[shown])}<div>{esc(text)}'
            f'<div class="ag-small">{esc(state)}</div></div></li>'
        )
    return '<ul class="ag-expect">' + "".join(items) + "</ul>"


def summary(sentences: list[str]) -> str:
    return f'<p class="ag-summary">{esc(" ".join(sentences))}</p>'


def meta_list(rows: list[tuple[str, str]]) -> str:
    """Label and value pairs, such as the provenance of an AI reply."""
    return '<dl class="ag-meta">' + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows) + "</dl>"


TRUST_CHIPS = (
    ("dataset", "Synthetic data only"),
    ("block", "Nothing is deployed or executed"),
    ("psychology", "The AI explains, it never decides"),
    ("visibility_off", "Labels never reach the model"),
    ("help", "Unknown is never reported as safe"),
    ("link", "Every fact links to a JSON line"),
)

FAQ = (
    (
        "Does it connect to a real AWS account?",
        "No. It reads two synthetic JSON snapshots. The only AWS call is to Amazon Bedrock, for the explanation text.",
    ),
    (
        "What does Amazon Bedrock do here?",
        "Nova Pro turns the evidence behind one finding into a short explanation. It sees placeholder IDs, never "
        "labels, and every ID it cites is checked. Anything else is discarded and a deterministic summary is shown.",
    ),
    (
        "What does Verified in this model mean?",
        "The engine reran the whole analysis with the permission revoked, the route disappeared, and every "
        "relationship stayed resolved. It is a statement about the synthetic model, not a guarantee for a real account.",
    ),
    (
        "Why is an unknown fact never treated as safe?",
        "If the snapshot does not say whether a permission exists, the engine cannot rule the route out. It reports "
        "the result as incomplete instead of guessing.",
    ),
    (
        "Can it block a pull request?",
        "Yes. The same engine runs as a command-line check that exits with an error when a change opens a new path or "
        "leaves the result incomplete. The repository's GitHub Actions workflow runs it on every pull request and marks "
        "the line responsible. The live demo shows it on the flagship change.",
    ),
    (
        "What is out of scope?",
        "Terraform and raw IAM policy parsing, EC2, general AssumeRole chains, multi-account analysis and automatic "
        "remediation. The model covers two rules: direct S3 reads and role use through a Lambda function.",
    ),
)
