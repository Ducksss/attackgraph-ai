"""HTML fragments and CSS for the Streamlit page, styled after the Protex template.

Streamlit sanitises st.html with DOMPurify and runs no JavaScript. Every
dynamic string still goes through esc(): labels and messages come from
uploaded files.
"""

from __future__ import annotations

import html

from .story import KIND_NAMES, Condition, Story

ICONS = {"principal": "person", "role": "badge", "lambda": "deployed_code", "s3_object": "description"}
PROTECTED_ICONS = {"privileged_role": "admin_panel_settings", "sensitive_object": "lock"}
STATE_ICONS = {"true": "check_circle", "false": "cancel", "unknown": "help"}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def icon(name: str, extra: str = "") -> str:
    return f'<span class="ag-icon {extra}" aria-hidden="true">{esc(name)}</span>'


CSS = """
<style>
:root {
  --ag-bg: #000d01;
  --ag-surface: #04130a;
  --ag-surface-2: #061a0c;
  --ag-line: #242424;
  --ag-line-2: #2b3a2e;
  --ag-text: #f2f5f2;
  --ag-muted: #a7aea8;
  --ag-dim: #748076;
  --ag-green: #53db78;
  --ag-green-fill: rgba(83, 219, 120, 0.3);
  --ag-green-soft: rgba(83, 219, 120, 0.08);
  --ag-amber: #ffc24b;
  --ag-amber-soft: rgba(255, 194, 75, 0.1);
  --ag-red: #ff7a7a;
  --ag-red-soft: rgba(255, 122, 122, 0.1);
  --ag-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { max-width: 1200px; padding-top: 1.25rem; padding-bottom: 4rem; }
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

.ag-nav { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 4px 0 16px; }
.ag-brand { display: flex; align-items: center; gap: 10px; color: var(--ag-text) !important; text-decoration: none !important;
  font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; font-size: 15px; }
.ag-logo { width: 34px; height: 34px; border-radius: 6px; background: var(--ag-green); color: #03250c; display: grid; place-items: center; }
.ag-logo .ag-icon { font-size: 22px; }
.ag-links { display: flex; gap: 2px; border: 1px solid var(--ag-line); border-radius: 4px; padding: 4px; }
.ag-links a { color: var(--ag-text) !important; text-decoration: none !important; padding: 6px 14px; border-radius: 4px; font-size: 15px; }
.ag-links a:hover { background: rgba(255, 255, 255, 0.05); }

.ag-btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 18px; border-radius: 4px; font-weight: 500;
  font-size: 16px; line-height: 24px; text-decoration: none !important; white-space: nowrap;
  transition: background-color 0.2s ease, border-color 0.2s ease, transform 0.1s ease; }
.ag-btn-primary { background: var(--ag-green-fill); border: 1px solid var(--ag-green); color: #fff !important; }
.ag-btn-primary:hover { background: rgba(83, 219, 120, 0.45); }
.ag-btn-ghost { background: rgba(255, 255, 255, 0.02); border: 1px solid var(--ag-line); color: var(--ag-text) !important; }
.ag-btn-ghost:hover { border-color: #3d4a3f; }
.ag-btn:active { transform: translateY(1px); }
.ag-btn:focus-visible, .ag-links a:focus-visible, .ag-brand:focus-visible, .ag-faq summary:focus-visible, .ag-gloss summary:focus-visible {
  outline: 2px solid var(--ag-green); outline-offset: 2px; }

.ag-hero { position: relative; overflow: hidden; text-align: center; border: 1px solid var(--ag-line); border-radius: 8px;
  padding: 72px 24px 44px;
  background:
    radial-gradient(55% 60% at 50% 30%, rgba(83, 219, 120, 0.18), transparent 70%),
    linear-gradient(rgba(83, 219, 120, 0.07) 1px, transparent 1px) 0 0 / 64px 64px,
    linear-gradient(90deg, rgba(83, 219, 120, 0.07) 1px, transparent 1px) 0 0 / 64px 64px,
    var(--ag-bg); }
.ag-pill { display: inline-flex; align-items: center; gap: 8px; padding: 4px 14px; border: 1px solid var(--ag-green);
  border-radius: 16px; font-size: 14px; color: var(--ag-text); background: rgba(0, 13, 1, 0.7); }
.ag-pill .ag-icon { color: var(--ag-green); font-size: 18px; }
.ag-hero h1 { font-size: clamp(34px, 3.7vw, 52px); line-height: 1.1; font-weight: 500; letter-spacing: -0.01em;
  margin: 22px auto 14px; padding: 0; color: var(--ag-text); max-width: 1100px; }
.ag-hero h1 .ag-soft { display: block; font-weight: 300; color: #dfe6df; }
.ag-lead { font-size: 20px; line-height: 30px; color: var(--ag-muted); max-width: 620px; margin: 0 auto; }
.ag-cta { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-top: 28px; }
.ag-hero-path { margin: 40px auto 0; max-width: 880px; }

.ag-statement { font-size: clamp(24px, 3vw, 38px); line-height: 1.35; font-weight: 400; text-align: center;
  max-width: 920px; margin: 96px auto 40px; color: var(--ag-text); }
.ag-statement span { color: #69746c; }

.ag-section { margin: 72px 0 28px; scroll-margin-top: 32px; }
.ag-section.center { text-align: center; }
.ag-tag { display: inline-block; padding: 3px 11px; border: 1px solid var(--ag-green); border-radius: 4px; color: var(--ag-green);
  font-size: 14px; font-weight: 600; }
.ag-h2 { font-size: clamp(30px, 3.6vw, 46px); line-height: 1.15; font-weight: 500; margin: 14px 0 12px; padding: 0; color: var(--ag-text); }
.ag-sub { color: var(--ag-muted); font-size: 18px; line-height: 28px; max-width: 680px; margin: 0; }
.ag-section.center .ag-sub { margin: 0 auto; }

.ag-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 8px; }
.ag-card { background: var(--ag-line); padding: 1px; border-radius: 8px; }
.ag-card-inner { background: rgba(0, 13, 1, 0.94); border-radius: 8px; padding: 32px 24px; height: 100%; box-sizing: border-box; }
.ag-art { height: 132px; display: flex; align-items: center; justify-content: center; gap: 0; margin-bottom: 28px;
  background: radial-gradient(50% 60% at 50% 50%, rgba(83, 219, 120, 0.12), transparent 70%); }
.ag-tile { width: 54px; height: 54px; border-radius: 8px; border: 1px solid rgba(83, 219, 120, 0.55); color: var(--ag-green);
  display: grid; place-items: center; background: linear-gradient(180deg, rgba(83, 219, 120, 0.2), rgba(83, 219, 120, 0.04));
  box-shadow: 0 0 22px rgba(83, 219, 120, 0.14); }
.ag-tile .ag-icon { font-size: 28px; }
.ag-tile.big { width: 68px; height: 68px; }
.ag-tile.big .ag-icon { font-size: 36px; }
.ag-tile.warn { border-color: rgba(255, 194, 75, 0.6); color: var(--ag-amber);
  background: linear-gradient(180deg, rgba(255, 194, 75, 0.18), rgba(255, 194, 75, 0.03)); box-shadow: 0 0 22px rgba(255, 194, 75, 0.12); }
.ag-wire { width: 34px; height: 1px; background: rgba(83, 219, 120, 0.6); }
.ag-card .ag-kicker { color: var(--ag-green); font-size: 14px; margin: 0 0 8px; }
.ag-card h3 { font-size: 23px; line-height: 1.35; font-weight: 500; margin: 0 0 8px; padding: 0; color: var(--ag-text); }
.ag-card p { color: var(--ag-muted); font-size: 16px; line-height: 1.6; margin: 0; }

.ag-verdict { display: flex; gap: 16px; align-items: flex-start; border: 1px solid; border-radius: 8px; padding: 20px 24px; margin: 8px 0 16px; }
.ag-verdict .ag-icon { font-size: 30px; margin-top: 2px; }
.ag-verdict h3 { margin: 0; padding: 0; font-size: 24px; line-height: 1.3; font-weight: 500; color: var(--ag-text); }
.ag-verdict p { margin: 6px 0 0; color: var(--ag-muted); font-size: 16px; line-height: 1.5; }
.ag-verdict.risk { border-color: rgba(255, 194, 75, 0.55); background: var(--ag-amber-soft); }
.ag-verdict.risk .ag-icon, .ag-verdict.unknown .ag-icon { color: var(--ag-amber); }
.ag-verdict.unknown { border-color: rgba(255, 194, 75, 0.45); background: rgba(255, 194, 75, 0.06); }
.ag-verdict.safe { border-color: rgba(83, 219, 120, 0.5); background: var(--ag-green-soft); }
.ag-verdict.safe .ag-icon { color: var(--ag-green); }
.ag-verdict.error { border-color: rgba(255, 122, 122, 0.55); background: var(--ag-red-soft); }
.ag-verdict.error .ag-icon { color: var(--ag-red); }
.ag-errors { margin: 10px 0 0; padding-left: 18px; color: var(--ag-text); }
.ag-errors li { margin: 4px 0; overflow-wrap: anywhere; }
.ag-errors code { font-family: var(--ag-mono); color: var(--ag-red); font-size: 13px; }

.ag-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 8px; }
.ag-stat { border: 1px solid var(--ag-line); border-radius: 8px; padding: 18px 20px; background: var(--ag-surface); }
.ag-stat-label { color: var(--ag-muted); font-size: 14px; }
.ag-stat-value { font-size: 30px; line-height: 1.2; font-weight: 500; margin-top: 6px; font-variant-numeric: tabular-nums; color: var(--ag-text); }
.ag-stat-note { color: var(--ag-dim); font-size: 13px; margin-top: 4px; overflow-wrap: anywhere; }
.ag-stat.risk .ag-stat-value { color: var(--ag-amber); }
.ag-stat.good .ag-stat-value { color: var(--ag-green); }
.ag-stats.two { grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 16px 0 4px; }
.ag-verdict.info { border-color: var(--ag-line-2); background: rgba(255, 255, 255, 0.015); }
.ag-verdict.info .ag-icon { color: var(--ag-muted); }

.ag-card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.ag-card-head .ag-icon { color: var(--ag-green); font-size: 22px; }
.ag-card-title { font-size: 22px; font-weight: 500; margin: 0; padding: 0; color: var(--ag-text); }
.ag-note { color: var(--ag-muted); font-size: 15px; line-height: 1.55; margin: 6px 0 0; }
.ag-small { color: var(--ag-dim); font-size: 13px; }
.ag-mono { font-family: var(--ag-mono); font-size: 13px; color: #9fe8b4; overflow-wrap: anywhere; }
.ag-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; border-radius: 4px; padding: 2px 8px;
  border: 1px solid; white-space: nowrap; }
.ag-badge.new { color: #221700; background: var(--ag-amber); border-color: var(--ag-amber); }
.ag-badge.green { color: var(--ag-green); border-color: rgba(83, 219, 120, 0.6); background: var(--ag-green-soft); }
.ag-badge.amber { color: var(--ag-amber); border-color: rgba(255, 194, 75, 0.6); background: var(--ag-amber-soft); }
.ag-badge.red { color: var(--ag-red); border-color: rgba(255, 122, 122, 0.6); background: var(--ag-red-soft); }
.ag-badge.gray { color: var(--ag-muted); border-color: var(--ag-line-2); }

.ag-change { border: 1px solid rgba(255, 194, 75, 0.55); background: var(--ag-amber-soft); border-radius: 8px; padding: 14px 16px; margin-top: 14px; }
.ag-change-text { font-size: 17px; line-height: 1.45; color: var(--ag-text); }
.ag-flip { display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; font-family: var(--ag-mono); font-size: 13px; }
.ag-flip .from { color: var(--ag-muted); text-decoration: line-through; }
.ag-flip .to { color: var(--ag-amber); font-weight: 600; }
.ag-gloss { margin-top: 14px; border: 1px solid var(--ag-line); border-radius: 8px; }
.ag-gloss summary { cursor: pointer; padding: 10px 14px; color: var(--ag-text); font-size: 15px; list-style: none; display: flex; align-items: center; gap: 8px; }
.ag-gloss summary::-webkit-details-marker { display: none; }
.ag-gloss summary .ag-icon { color: var(--ag-green); font-size: 18px; }
.ag-gloss p { margin: 0; padding: 0 14px 12px; color: var(--ag-muted); font-size: 15px; line-height: 1.55; }

.ag-path { display: flex; align-items: stretch; flex-wrap: wrap; row-gap: 14px; margin: 16px 0 6px; }
.ag-node { flex: 1 1 120px; min-width: 112px; max-width: 240px; border: 1px solid var(--ag-line-2); border-radius: 8px; padding: 12px 14px;
  background: var(--ag-surface); box-sizing: border-box; }
.ag-node-kind { display: flex; align-items: center; gap: 6px; color: var(--ag-muted); font-size: 12px; }
.ag-node-kind .ag-icon { font-size: 18px; color: var(--ag-green); }
.ag-node-label { font-size: 15px; line-height: 1.35; font-weight: 500; margin-top: 6px; color: var(--ag-text); overflow-wrap: anywhere; }
.ag-node-id { font-family: var(--ag-mono); font-size: 11.5px; color: var(--ag-dim); margin-top: 4px; overflow-wrap: anywhere; }
.ag-node.protected { border-color: rgba(255, 194, 75, 0.75); box-shadow: 0 0 0 1px rgba(255, 194, 75, 0.2), 0 0 26px rgba(255, 194, 75, 0.12); }
.ag-node.protected .ag-node-kind, .ag-node.protected .ag-node-kind .ag-icon { color: var(--ag-amber); }
.ag-node.faded, .ag-hop.faded { opacity: 0.42; }
.ag-hop { flex: 1 1 84px; min-width: 72px; box-sizing: border-box; display: flex; flex-direction: column; justify-content: center;
  padding: 0 8px; text-align: center; }
.ag-hop-text { font-size: 12.5px; line-height: 1.3; color: var(--ag-muted); margin-bottom: 7px; overflow-wrap: anywhere; }
.ag-hop-badge { align-self: center; margin-bottom: 6px; font-size: 11px; padding: 1px 7px; }
.ag-hop-line { height: 2px; background: var(--ag-green); position: relative; margin-right: 6px; }
.ag-hop-line::after { content: ""; position: absolute; right: -7px; top: -5px; border-left: 8px solid var(--ag-green);
  border-top: 6px solid transparent; border-bottom: 6px solid transparent; }
.ag-hop.new .ag-hop-text { color: var(--ag-amber); font-weight: 600; }
.ag-hop.new .ag-hop-line { background: var(--ag-amber); }
.ag-hop.new .ag-hop-line::after { border-left-color: var(--ag-amber); }
.ag-hop.cut .ag-hop-text { color: var(--ag-red); font-weight: 600; }
.ag-hop.cut .ag-hop-line { background: repeating-linear-gradient(90deg, var(--ag-red) 0 6px, transparent 6px 11px); }
.ag-hop.cut .ag-hop-line::after { border-left-color: var(--ag-red); }
.ag-hop.maybe .ag-hop-line { background: repeating-linear-gradient(90deg, var(--ag-amber) 0 6px, transparent 6px 11px); }
.ag-hop.maybe .ag-hop-line::after { border-left-color: var(--ag-amber); }
@media (prefers-reduced-motion: no-preference) {
  .ag-hop.new .ag-hop-line { animation: ag-pulse 2.6s ease-in-out infinite; }
}
@keyframes ag-pulse { 0%, 100% { box-shadow: 0 0 0 rgba(255, 194, 75, 0); } 50% { box-shadow: 0 0 12px rgba(255, 194, 75, 0.75); } }
.ag-path.compact .ag-node { padding: 10px 12px; }
.ag-path.compact .ag-node-id { display: none; }

.ag-conds { list-style: none; padding: 0 !important; margin: 10px 0 0 !important; display: grid; gap: 8px; }
.ag-conds li { margin: 0 !important; }
.ag-cond { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--ag-line); border-radius: 8px;
  background: rgba(255, 255, 255, 0.012); }
.ag-cond > .ag-icon { font-size: 20px; margin-top: 1px; }
.ag-cond.true > .ag-icon { color: var(--ag-green); }
.ag-cond.false > .ag-icon { color: var(--ag-red); }
.ag-cond.unknown > .ag-icon { color: var(--ag-amber); }
.ag-cond.changed { border-color: rgba(255, 194, 75, 0.6); background: var(--ag-amber-soft); }
.ag-cond-text { color: var(--ag-text); font-size: 15px; line-height: 1.45; overflow-wrap: anywhere; }
.ag-cond-meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 4px; }
.ag-step-title { font-size: 15px; font-weight: 600; margin: 18px 0 2px; color: var(--ag-text); }

.ag-summary { color: var(--ag-text); font-size: 16px; line-height: 1.6; margin: 8px 0 0; }
.ag-expect { list-style: none; padding: 0 !important; margin: 10px 0 0 !important; display: grid; gap: 6px; }
.ag-expect li { margin: 0 !important; display: flex; gap: 8px; align-items: flex-start; color: var(--ag-text); font-size: 15px; line-height: 1.45; }
.ag-expect li .ag-icon { font-size: 19px; color: var(--ag-green); margin-top: 1px; }
.ag-expect li.fail .ag-icon { color: var(--ag-red); }
.ag-expect li.inconclusive .ag-icon { color: var(--ag-amber); }
[class*="st-key-agcard-"] { background: var(--ag-surface); border: 1px solid var(--ag-line); border-radius: 8px; padding: 24px 24px 20px; }
.st-key-agcard-change { border-color: rgba(255, 194, 75, 0.35); }

[data-testid="stBaseButton-primary"] { background: var(--ag-green-fill) !important; border: 1px solid var(--ag-green) !important; color: #fff !important; }
[data-testid="stBaseButton-primary"]:hover { background: rgba(83, 219, 120, 0.45) !important; }
[data-testid="stBaseButton-secondary"] { background: rgba(255, 255, 255, 0.02) !important; border: 1px solid var(--ag-line) !important; color: var(--ag-text) !important; }
[data-testid="stBaseButton-secondary"]:hover { border-color: #3d4a3f !important; }
[data-testid="stExpander"] details { border-color: var(--ag-line) !important; background: rgba(255, 255, 255, 0.012); }

.ag-trust { scroll-margin-top: 32px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 40px; align-items: start; }
.ag-chips { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }
.ag-chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border: 1px solid rgba(83, 219, 120, 0.6); border-radius: 16px;
  font-size: 14px; color: var(--ag-text); }
.ag-chip .ag-icon { color: var(--ag-green); font-size: 18px; }
.ag-faq details { border: 1px solid var(--ag-line); border-radius: 8px; margin-bottom: 10px; background: rgba(255, 255, 255, 0.012); }
.ag-faq summary { cursor: pointer; list-style: none; padding: 16px 20px; font-weight: 500; font-size: 16px; color: var(--ag-text);
  display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.ag-faq summary::-webkit-details-marker { display: none; }
.ag-faq summary::after { content: "add"; font-family: "Material Symbols Rounded"; font-size: 22px; color: var(--ag-muted); font-feature-settings: "liga"; }
.ag-faq details[open] summary::after { content: "remove"; }
.ag-faq details p { margin: 0; padding: 0 20px 18px; color: var(--ag-muted); font-size: 15px; line-height: 1.6; }

.ag-footer { margin-top: 88px; padding-top: 22px; border-top: 1px solid var(--ag-line); display: flex; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; color: var(--ag-dim); font-size: 14px; }

@media (max-width: 900px) {
  .ag-cards, .ag-trust { grid-template-columns: 1fr; }
  .ag-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ag-links { display: none; }
  .ag-hero { padding: 48px 16px 32px; }
}
@media (max-width: 640px) {
  .ag-brand { letter-spacing: 0.06em; font-size: 13px; }
  .ag-path { flex-direction: column; flex-wrap: nowrap; }
  .ag-node { max-width: none; flex: none; }
  .ag-hop { flex: none; flex-direction: row; align-items: center; justify-content: flex-start; gap: 12px; padding: 4px 0 4px 20px; text-align: left; min-height: 48px; }
  .ag-hop-text { margin: 0; order: 3; }
  .ag-hop-badge { order: 2; margin: 0; }
  .ag-hop-line { width: 2px; height: 34px; margin: 0 0 8px; order: 1; flex: none; }
  .ag-hop-line::after { right: -5px; top: auto; bottom: -8px; border-left: 6px solid transparent; border-right: 6px solid transparent;
    border-top: 8px solid var(--ag-green); border-bottom: 0; }
  .ag-hop.new .ag-hop-line::after, .ag-hop.maybe .ag-hop-line::after { border-left-color: transparent; border-top-color: var(--ag-amber); }
  .ag-hop.cut .ag-hop-line::after { border-left-color: transparent; border-top-color: var(--ag-red); }
  .ag-hop.cut .ag-hop-line { background: repeating-linear-gradient(180deg, var(--ag-red) 0 6px, transparent 6px 11px); }
  .ag-hop.maybe .ag-hop-line { background: repeating-linear-gradient(180deg, var(--ag-amber) 0 6px, transparent 6px 11px); }
}
</style>
"""


def nav() -> str:
    return (
        '<nav class="ag-nav" aria-label="Page">'
        f'<a class="ag-brand" href="#ag-top"><span class="ag-logo">{icon("conversion_path")}</span>AttackGraph AI</a>'
        '<div class="ag-links"><a href="#ag-how">How it works</a><a href="#ag-trust">Trust and limits</a></div>'
        '<a class="ag-btn ag-btn-primary" href="#ag-demo">See the demo</a>'
        "</nav>"
    )


def hero(preview: str) -> str:
    return (
        '<section class="ag-hero" id="ag-top">'
        f'<span class="ag-pill">{icon("verified_user")}Pre-deployment IAM review, explained by Amazon Bedrock</span>'
        '<h1>See what a permission change unlocks<span class="ag-soft">before you deploy it</span></h1>'
        '<p class="ag-lead">AttackGraph AI finds new paths to admin roles and sensitive data in a proposed cloud change, '
        "then proves the fix.</p>"
        '<div class="ag-cta"><a class="ag-btn ag-btn-primary" href="#ag-demo">See the demo</a>'
        '<a class="ag-btn ag-btn-ghost" href="#ag-how">How it works</a></div>'
        f'<div class="ag-hero-path">{preview}</div>'
        "</section>"
    )


def statement() -> str:
    return (
        '<p class="ag-statement">One line in a pull request can turn a build pipeline into an administrator. '
        "<span>Reviewers see the line. AttackGraph AI shows the path it opens, and whether a fix closes it.</span></p>"
    )


def section_head(title: str, sub: str = "", tag: str = "", anchor: str = "", center: bool = False) -> str:
    return (
        f'<div class="ag-section{" center" if center else ""}"' + (f' id="{esc(anchor)}"' if anchor else "") + ">"
        + (f'<span class="ag-tag">{esc(tag)}</span>' if tag else "")
        + f'<h2 class="ag-h2">{esc(title)}</h2>'
        + (f'<p class="ag-sub">{esc(sub)}</p>' if sub else "")
        + "</div>"
    )


def _card(art: str, kicker: str, title: str, body: str) -> str:
    return (
        f'<div class="ag-card"><div class="ag-card-inner"><div class="ag-art">{art}</div>'
        f'<p class="ag-kicker">{esc(kicker)}</p><h3>{esc(title)}</h3><p>{esc(body)}</p></div></div>'
    )


def _tile(name: str, cls: str = "") -> str:
    return f'<div class="ag-tile {cls}">{icon(name)}</div>'


WIRE = '<div class="ag-wire"></div>'


def how_it_works() -> str:
    cards = [
        _card(
            _tile("person") + WIRE + _tile("deployed_code") + WIRE + _tile("admin_panel_settings", "warn"),
            "Deterministic rules",
            "Map every route",
            "The engine links permissions into routes from an entry point to protected roles and data. "
            "A missing fact stays unknown, never safe.",
        ),
        _card(
            _tile("data_object") + WIRE + _tile("auto_awesome", "big") + WIRE + _tile("notes"),
            "Amazon Bedrock",
            "Explain it in plain English",
            "Nova Pro writes a short explanation from anonymised evidence. It cannot add findings, change severity "
            "or invent fixes.",
        ),
        _card(
            _tile("key_off", "warn") + WIRE + _tile("verified_user", "big"),
            "Proof, not advice",
            "Test the fix",
            "Revoke the new permission on a copy, rerun the analysis, and confirm the route is gone while normal "
            "access still works.",
        ),
    ]
    return '<div class="ag-cards">' + "".join(cards) + "</div>"


def path(story: Story, mode: str = "live", compact: bool = False) -> str:
    """The route as node cards joined by labelled arrows.

    mode "live" marks changed hops as new and dashes unresolved ones;
    "simulated" and "closed" mark changed hops as revoked or removed and fade
    everything after the cut.
    """
    parts = []
    cut = False
    for i, node in enumerate(story.nodes):
        if i:
            hop = story.hops[i - 1]
            cls, tag = "", ""
            if cut:
                cls = "faded"
            elif mode == "simulated" and hop.changed:
                cls, tag, cut = "cut", ("red", "Revoked"), True
            elif mode == "closed" and hop.changed:
                cls, tag, cut = "cut", ("red", "Removed"), True
            elif hop.state == "unknown":
                cls, tag = "maybe", ("amber", "Unknown") if hop.changed else ""
            elif hop.changed:
                cls, tag = "new", ("new", "New")
            elif hop.state != "true":
                cls = "maybe"
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
    return f'<div class="ag-path{" compact" if compact else ""}" role="img" aria-label="{label}">' + "".join(parts) + "</div>"


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


def conditions(story: Story) -> str:
    """One checklist per step; step titles only appear when the route has several steps."""
    out = []
    several = len(story.steps) > 1
    for step in story.steps:
        if several:
            held = sum(1 for c in step.conditions if c.state == "true")
            out.append(f'<div class="ag-step-title">{esc(step.title)}</div>')
            out.append(f'<div class="ag-small">{held} of {len(step.conditions)} conditions hold.</div>')
        out.append('<ul class="ag-conds">' + "".join(condition_item(c) for c in step.conditions) + "</ul>")
    return "".join(out)


def change_block(story: Story) -> str:
    if not story.changes:
        return '<p class="ag-note">No fact on this route changed between the snapshots.</p>'
    blocks = []
    for change in story.changes:
        before, after = change.change.split(" → ")
        blocks.append(
            f'<div class="ag-change"><div class="ag-change-text">{esc(change.text)}</div>'
            f'<div class="ag-flip"><span class="from">{esc(before)}</span>{icon("arrow_forward")}'
            f'<span class="to">{esc(after)}</span></div>'
            f'<div class="ag-small" style="margin-top:6px">Fact <span class="ag-mono">{esc(change.fact_id)}</span> at '
            f'<span class="ag-mono">{esc(change.pointers[0] if change.pointers else "-")}</span></div></div>'
        )
    return "".join(blocks)


PASSROLE_GLOSSARY = (
    '<details class="ag-gloss"><summary>' + icon("school") + "What is iam:PassRole?</summary>"
    "<p>It is the permission to hand an IAM role to an AWS service. If someone can hand a powerful role to a Lambda "
    "function they write and run, their code runs with that role's permissions. That is why this one permission "
    "matters.</p></details>"
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
        "What is out of scope?",
        "Terraform and raw IAM policy parsing, EC2, general AssumeRole chains, multi-account analysis and automatic "
        "remediation. The model covers two rules: direct S3 reads and role use through a Lambda function.",
    ),
)


def trust() -> str:
    chips = "".join(f'<span class="ag-chip">{icon(g)}{esc(t)}</span>' for g, t in TRUST_CHIPS)
    faq = "".join(f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>" for q, a in FAQ)
    return (
        '<div class="ag-trust" id="ag-trust"><div>'
        '<h2 class="ag-h2">Built to be checked</h2>'
        '<p class="ag-sub">Every result traces back to a line in the input files, and the limits are stated up front.</p>'
        f'<div class="ag-chips">{chips}</div></div>'
        f'<div class="ag-faq">{faq}</div></div>'
    )


def footer() -> str:
    return (
        '<footer class="ag-footer"><span>AttackGraph AI. Built for the AWS Build Beyond Student AI Demo Challenge 2026.</span>'
        "<span>Streamlit, NetworkX and Amazon Bedrock. Synthetic data only.</span></footer>"
    )


RESULT_ICONS = {"pass": "check_circle", "fail": "cancel", "inconclusive": "help"}


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
