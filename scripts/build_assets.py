"""Render the README screenshots, the brand kit and the Devpost images.

The product screenshots are crops of the static build in site/, so rebuild it
first. The logo, palette, social preview, Devpost thumbnail and gallery cards
are HTML pages drawn with the CSS tokens from attackgraph/web.py. Headless
Chrome renders everything through scripts/assets/shoot.mjs, which needs
Node 22 or newer and Google Chrome (set CHROME to its path if it is not
found). The pages load their fonts from Google Fonts.

A file is replaced only when it changed visibly. Fresh renders differ from the
committed ones by anti-aliasing noise, so a pixel counts as changed only when
one of its channels moves by more than NOISE levels.

Usage:
    python scripts/build_site.py && python scripts/build_assets.py
    python scripts/build_assets.py --force    # replace every file
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SHOOT = ROOT / "scripts" / "assets" / "shoot.mjs"
NOISE = 24  # the largest per-channel difference that is still anti-aliasing noise
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Marks the bordered card that holds a visible h3 with exactly this text, so it can be cropped.
TAG = """window.__tag = (text, tag) => {
  const h = [...document.querySelectorAll('h3')].find((e) => e.textContent.trim() === text && e.offsetParent !== null);
  if (!h) throw new Error('heading not found: ' + text);
  let el = h;
  while (el && !(parseFloat(getComputedStyle(el).borderTopWidth) > 0 && el.getBoundingClientRect().width > 800)) el = el.parentElement;
  if (!el) throw new Error('card not found: ' + text);
  el.setAttribute('data-shoot', tag);
};"""
SIMULATE = "document.querySelector('.ag-scenario[data-scenario=passrole]').dataset.simulated = 'true';"
VERDICT = "document.querySelector('.ag-scenario[data-scenario=passrole] .ag-verdict').setAttribute('data-shoot', 'verdict');"

# Product screenshots: page under site/, script run before the crop, element or elements to crop.
SHOTS = {
    "hero": ("index.html", "", ".ag-hero"),
    "pr-failed": ("demo/index.html", "__tag('The pull request', 'pr')", "[data-shoot=pr]"),
    "path-change": ("demo/index.html", "__tag('The path it opens', 'path'); __tag('The change', 'change')",
                    ["[data-shoot=path]", "[data-shoot=change]"]),
    "verdict-path": ("demo/index.html", VERDICT + "__tag('The path it opens', 'path')", ["[data-shoot=verdict]", "[data-shoot=path]"]),
    "ai": ("demo/index.html", "__tag('What this means', 'ai')", "[data-shoot=ai]"),
    "fix": ("demo/index.html", SIMULATE + "__tag('The fix', 'fix')", "[data-shoot=fix]"),
    "pr-passed": ("demo/index.html", SIMULATE + "__tag('The pull request', 'pr')", "[data-shoot=pr]"),
}
# The screenshots the README shows, by their file name in docs/images/.
README_SHOTS = {"hero": "hero.png", "pr-failed": "pull-request.png", "verdict-path": "demo.png", "ai": "explanation.png", "fix": "fix.png"}

MARK_BODY = (
    '<rect width="64" height="64" rx="14" fill="#6366f1"/>'
    '<path d="M17.5 46.5C31.5 46.5 43.5 45.5 43.5 32.5" fill="none" stroke="#fcd34d" stroke-width="5" stroke-linecap="round"/>'
    '<circle cx="17.5" cy="46.5" r="6" fill="#fff"/>'
    '<path d="M43.5 11.5 52.5 14.9V21.1C52.5 26.5 48.8 30.4 43.5 32.5 38.2 30.4 34.5 26.5 34.5 21.1V14.9Z" fill="#fff"/>'
)
MARK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="AttackGraph AI">'
    f"<title>AttackGraph AI</title>{MARK_BODY}</svg>\n"
)


def mark(size: str = "1.55em") -> str:
    return f'<svg viewBox="0 0 64 64" style="width:{size};height:{size};flex:none" aria-hidden="true">{MARK_BODY}</svg>'


HEAD = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,400,0,0&display=block" rel="stylesheet">
<style>
:root { --bg:#f9f9fa; --surface:#fff; --surface2:#f4f4f6; --line:#e2e2e8; --line2:#ececf1; --ink:#111114; --body:#3a3a44;
  --muted:#5f5f72; --soft:#9999a8; --indigo:#6366f1; --indigo-strong:#4044f0; --indigo-soft:#eef0ff; --indigo-line:#c7cafd;
  --amber:#d97706; --amber-text:#b45309; --amber-soft:#fffbeb; --amber-line:#fcd34d; --red:#dc2626; --red-text:#b91c1c;
  --red-soft:#fef2f2; --red-line:#fca5a5; --green:#16a34a; --green-text:#15803d; --green-soft:#f0fdf4; --green-line:#86efac;
  --mono:"JetBrains Mono", ui-monospace, monospace; }
* { box-sizing: border-box; }
html, body { margin: 0; background: transparent; }
body { font-family: Inter, system-ui, sans-serif; color: var(--ink); -webkit-font-smoothing: antialiased; }
.ms { font-family: "Material Symbols Rounded"; font-weight: normal; font-style: normal; line-height: 1; letter-spacing: normal;
  display: inline-block; white-space: nowrap; -webkit-font-feature-settings: "liga"; }
.canvas { position: relative; overflow: hidden; background: var(--bg); }
.dots::before { content: ""; position: absolute; inset: 0; pointer-events: none;
  background-image: radial-gradient(#d9d9e1 1.1px, transparent 1.3px); background-size: 24px 24px;
  -webkit-mask-image: radial-gradient(ellipse at 78% 92%, #000 18%, transparent 72%); }
.lockup { display: inline-flex; align-items: center; gap: .42em; font-weight: 700; letter-spacing: -0.02em; line-height: 1; white-space: nowrap; }
.badge { display: inline-flex; align-items: center; gap: .3em; font-weight: 600; border-radius: 999px; border: 1px solid; white-space: nowrap; }
.badge.amber { color: var(--amber-text); background: var(--amber-soft); border-color: var(--amber-line); }
.badge.red { color: var(--red-text); background: var(--red-soft); border-color: var(--red-line); }
.badge.green { color: var(--green-text); background: var(--green-soft); border-color: var(--green-line); }
.badge.indigo { color: var(--indigo-strong); background: var(--indigo-soft); border-color: var(--indigo-line); }
.badge.plain { color: var(--body); background: var(--surface); border-color: var(--line); }
/* The route, drawn like the app's path card. --u scales it. */
.route { --u: 1px; display: flex; align-items: center; }
.node { flex: 1 1 0; background: var(--surface); border: 1px solid var(--line); border-radius: calc(10 * var(--u));
  padding: calc(14 * var(--u)) calc(16 * var(--u)); box-shadow: 0 2px 6px rgba(16,24,40,.06); min-width: 0; }
.node.protected { border-color: var(--amber-line); box-shadow: 0 0 0 calc(3 * var(--u)) rgba(245,158,11,.14), 0 2px 6px rgba(16,24,40,.06); }
.kind { display: flex; align-items: center; gap: calc(6 * var(--u)); color: var(--muted); font-size: calc(13 * var(--u)); font-weight: 500; }
.kind .ms { font-size: calc(17 * var(--u)); color: var(--indigo); }
.node.protected .kind, .node.protected .kind .ms { color: var(--amber-text); }
.label { font-size: calc(18 * var(--u)); font-weight: 600; letter-spacing: -0.01em; margin-top: calc(6 * var(--u)); line-height: 1.25; }
.nid { font-family: var(--mono); font-size: calc(12 * var(--u)); color: var(--soft); margin-top: calc(6 * var(--u)); }
.hop { flex: 0 0 calc(150 * var(--u)); display: flex; flex-direction: column; align-items: center; padding: 0 calc(10 * var(--u)); }
.hop .badge { font-size: calc(12 * var(--u)); padding: calc(2 * var(--u)) calc(9 * var(--u)); margin-bottom: calc(5 * var(--u)); }
.hop-text { font-size: calc(13 * var(--u)); color: var(--muted); text-align: center; line-height: 1.3; margin-bottom: calc(7 * var(--u)); }
.hop.new .hop-text { color: var(--amber-text); font-weight: 600; }
.line { align-self: stretch; height: calc(2 * var(--u)); background: var(--indigo); position: relative; margin-right: calc(7 * var(--u)); }
.line::after { content: ""; position: absolute; right: calc(-8 * var(--u)); top: calc(-5 * var(--u));
  border-left: calc(9 * var(--u)) solid var(--indigo); border-top: calc(6 * var(--u)) solid transparent; border-bottom: calc(6 * var(--u)) solid transparent; }
.route .node { flex: 0 0 auto; } .route .label { white-space: nowrap; } .route .hop { flex: 1 1 0; min-width: calc(120 * var(--u)); }
.hop.new .line { background: var(--amber); } .hop.new .line::after { border-left-color: var(--amber); }
</style></head><body>"""

ROUTE = """<div class="route" style="--u:{u}px">
  <div class="node"><div class="kind"><span class="ms">person</span>Entry point</div><div class="label">{entry}</div><div class="nid">p-ci-deployer</div></div>
  <div class="hop new"><span class="badge amber">New</span><div class="hop-text">{hop}</div><div class="line"></div></div>
  <div class="node"><div class="kind"><span class="ms">deployed_code</span>Lambda function</div><div class="label">{via}</div><div class="nid">l-build-hook</div></div>
  <div class="hop"><div class="hop-text">runs as</div><div class="line"></div></div>
  <div class="node protected"><div class="kind"><span class="ms">admin_panel_settings</span>Protected role</div><div class="label">Deployment admin role</div><div class="nid">r-deploy-admin</div></div>
</div>"""
SHORT = {"entry": "CI deploy user", "hop": "can pass the admin role to", "via": "Post-build hook"}

SWATCHES = [
    ("Indigo", "#6366f1", "Brand, established relationships, links"),
    ("Indigo strong", "#4044f0", "Pressed states, text on indigo soft"),
    ("Ink", "#111114", "Headlines and the wordmark"),
    ("Body", "#3a3a44", "Running text"),
    ("Muted", "#5f5f72", "Secondary text"),
    ("Background", "#f9f9fa", "Page background"),
    ("Line", "#e2e2e8", "Borders and dividers"),
    ("Amber", "#d97706", "New or changed: what flipped"),
    ("Signal amber", "#fcd34d", "The changed link inside the mark"),
    ("Green", "#16a34a", "Verified fix, check passed"),
    ("Red", "#dc2626", "Revoked, check failed"),
]

# Devpost gallery: real screens, 3:2, one message each.
GALLERY = [
    ("01-the-idea", "hero", "The idea", "One changed permission can open a route to admin",
     "AttackGraph AI checks what a cloud permission change completes, not just the line that changed."),
    ("02-blocked-pull-request", "pr-failed", "Pull-request check", "Blocked on the exact line that opens the route",
     "The GitHub Actions check fails and marks line 27 with the route it opens and the verified fix."),
    ("03-the-path", "path-change", "The analysis", "The path it opens, and the one fact that flipped",
     "CI deploy user to post-build hook to deployment admin role. All 7 conditions hold; one changed."),
    ("04-amazon-bedrock", "ai", "Amazon Bedrock", "Nova Pro explains it; the engine decides",
     "The model sees placeholder IDs only. Every ID it cites is checked, and it cannot add findings or fixes."),
    ("05-verified-fix", "fix", "The fix", "Revoke one grant; the fix is verified in this model",
     "Rerun on a copy: high-risk paths 1 to 0, and both normal access checks still pass."),
    ("06-check-passes", "pr-passed", "Pull-request check", "The fix commit passes the same check",
     "Revert the one line and the check reports no new modelled high-risk access, exit status 0."),
]
FRAME_TOP, FRAME_W, FRAME_H = 188, 1104, 572

STEPS = [
    ("description", "Two snapshots", "Current and proposed configuration as synthetic JSON."),
    ("rule", "Validate", "Size, encoding, schema and references. Errors point at a JSON line."),
    ("conversion_path", "Derive routes", "Two explicit rules, three-valued logic, NetworkX witnesses."),
    ("compare_arrows", "Compare", "Added, removed, unchanged or inconclusive, by finding identity."),
    ("healing", "Verify the fix", "Revoke each new grant on a copy and rerun the whole analysis."),
]
OUTPUTS = [
    ("web", "Live demo and report", "Streamlit app, static site on Vercel and a Markdown report built from the same objects.", False),
    ("fact_check", "Pull-request check", "python -m attackgraph in GitHub Actions: exit status 1 and a note on the changed line.", False),
    ("auto_awesome", "Amazon Bedrock explanation", "Nova Pro via Converse sees an aliased evidence packet. A reply citing anything else is rejected.", True),
]


def header(eyebrow: str, title: str, caption: str) -> str:
    return f"""<div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div><div style="font-size:16px;font-weight:600;color:var(--indigo)">{eyebrow}</div>
      <div style="font-size:36px;font-weight:700;letter-spacing:-0.025em;line-height:1.12;margin-top:8px">{title}</div>
      <div style="font-size:18px;color:var(--muted);line-height:1.45;margin-top:10px;max-width:1010px">{caption}</div></div>
    <div class="lockup" style="font-size:17px;color:var(--body);margin-top:2px">{mark()}AttackGraph AI</div></div>"""


def shot_jobs(shots: Path) -> list[dict]:
    return [
        {"url": (SITE / page).as_uri(), "out": str(shots / f"{name}.png"), "width": 1280, "height": 900, "scale": 2,
         "wait": 1200, "js": TAG + script, "selector": selector}
        for name, (page, script, selector) in SHOTS.items()
    ]


def asset_jobs(pages: Path, shots: Path, out: Path) -> list[dict]:
    """Write mark.svg and the brand and Devpost pages; return their render jobs, with outputs under out."""
    brand, devpost = out / "docs" / "brand", out / "docs" / "devpost"
    brand.mkdir(parents=True)
    pages.mkdir(parents=True)
    (brand / "mark.svg").write_text(MARK_SVG, encoding="utf-8")

    def page(name: str, body: str) -> str:
        path = pages / f"{name}.html"
        path.write_text(HEAD + body + "</body></html>", encoding="utf-8")
        return path.as_uri()

    url = page("mark", f'<div id="m" style="width:512px;height:512px">{mark("512px")}</div>')
    jobs = [{"url": url, "out": str(brand / "mark-512.png"), "width": 600, "height": 600, "scale": 1, "transparent": True, "selector": "#m"}]
    for name, color in (("logo", "var(--ink)"), ("logo-dark", "#ffffff")):
        url = page(name, f'<div style="padding:24px"><div id="l" class="lockup" style="font-size:64px;color:{color}">{mark()}AttackGraph AI</div></div>')
        jobs.append({"url": url, "out": str(brand / f"{name}.png"), "width": 900, "height": 200, "scale": 2, "transparent": True, "selector": "#l"})

    cells = "".join(
        f'<div style="display:flex;gap:16px;align-items:center"><div style="width:64px;height:64px;border-radius:12px;background:{h};'
        f'border:1px solid rgba(17,17,20,.08)"></div><div><div style="font-weight:700;font-size:17px">{n}</div>'
        f'<div style="font-family:var(--mono);font-size:14px;color:var(--muted);margin-top:3px">{h}</div>'
        f'<div style="font-size:14px;color:var(--muted);margin-top:3px">{r}</div></div></div>'
        for n, h, r in SWATCHES
    )
    url = page("palette", f"""<div id="p" class="canvas" style="width:1200px;padding:48px 56px 52px">
  <div class="lockup" style="font-size:26px">{mark()}AttackGraph AI</div>
  <div style="font-size:34px;font-weight:700;letter-spacing:-0.02em;margin-top:28px">Colour and type</div>
  <div style="font-size:17px;color:var(--muted);margin-top:6px">Colour carries meaning here: amber is what changed, red is what was revoked or failed, green is what was verified.</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:26px 28px;margin-top:34px">{cells}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:40px;padding-top:30px;border-top:1px solid var(--line)">
    <div><div style="font-size:14px;color:var(--muted);font-weight:500">Interface and headlines</div>
      <div style="font-size:40px;font-weight:700;letter-spacing:-0.02em;margin-top:8px">Inter</div>
      <div style="font-size:17px;color:var(--body);margin-top:6px">Regular 400, Medium 500, Semibold 600, Bold 700</div></div>
    <div><div style="font-size:14px;color:var(--muted);font-weight:500">IDs, JSON pointers and code</div>
      <div style="font-family:var(--mono);font-size:34px;font-weight:500;margin-top:10px">f-ci-pass-deploy-admin</div>
      <div style="font-size:17px;color:var(--body);margin-top:8px">JetBrains Mono, Regular 400 and Medium 500</div></div>
  </div>
</div>""")
    jobs.append({"url": url, "out": str(brand / "palette.png"), "width": 1200, "height": 800, "scale": 2, "selector": "#p"})

    url = page("social", f"""<div class="canvas dots" style="width:1280px;height:640px;padding:60px 72px">
  <div class="lockup" style="font-size:30px">{mark()}AttackGraph AI</div>
  <div style="font-size:54px;font-weight:700;letter-spacing:-0.03em;line-height:1.06;margin-top:38px;max-width:900px">
    Ship permission changes<br>without shipping admin access.</div>
  <div style="font-size:21px;color:var(--muted);line-height:1.45;margin-top:18px;max-width:900px">
    Finds the route one IAM change opens, explains it with Amazon Bedrock, tests the fix and blocks the pull request.</div>
  <div style="position:absolute;left:72px;right:72px;bottom:64px">{ROUTE.format(u=1, **SHORT)}</div>
</div>""")
    jobs.append({"url": url, "out": str(brand / "social-preview.png"), "width": 1280, "height": 640, "scale": 1})

    url = page("thumbnail", f"""<div class="canvas dots" style="width:1200px;height:800px;padding:68px 72px">
  <div class="lockup" style="font-size:40px">{mark()}AttackGraph AI</div>
  <div style="font-size:70px;font-weight:700;letter-spacing:-0.035em;line-height:1.03;margin-top:48px">
    Ship permission changes<br>without shipping admin access.</div>
  <div style="display:flex;gap:12px;margin-top:30px">
    <span class="badge red" style="font-size:19px;padding:6px 16px"><span class="ms" style="font-size:22px">cancel</span>Pull request blocked</span>
    <span class="badge green" style="font-size:19px;padding:6px 16px"><span class="ms" style="font-size:22px">check_circle</span>Fix verified</span>
    <span class="badge indigo" style="font-size:19px;padding:6px 16px"><span class="ms" style="font-size:22px">auto_awesome</span>Explained by Amazon Bedrock</span>
  </div>
  <div style="position:absolute;left:72px;right:72px;bottom:70px">{ROUTE.format(u=1.25, **SHORT)}</div>
</div>""")
    jobs.append({"url": url, "out": str(devpost / "thumbnail.png"), "width": 1200, "height": 800, "scale": 2})

    for name, shot, eyebrow, title, caption in GALLERY:
        png = shots / f"{shot}.png"
        w, h = Image.open(png).size
        scale = min(FRAME_W / (w / 2), FRAME_H / (h / 2))  # shots are 2x
        dw, dh = round(w / 2 * scale), round(h / 2 * scale)
        url = page(name, f"""<div class="canvas" style="width:1200px;height:800px;padding:48px 48px 0">
  {header(eyebrow, title, caption)}
  <img src="{png.as_uri()}" style="position:absolute;left:{(1200 - dw) // 2}px;top:{FRAME_TOP}px;width:{dw}px;height:{dh}px;
    border-radius:{12 * scale:.1f}px;box-shadow:0 18px 40px rgba(16,24,40,.10),0 2px 6px rgba(16,24,40,.06)">
</div>""")
        jobs.append({"url": url, "out": str(devpost / "gallery" / f"{name}.png"), "width": 1200, "height": 800, "scale": 2})

    step_html = ""
    for i, (icon, title, text) in enumerate(STEPS):
        if i:
            step_html += '<div style="display:flex;align-items:center;color:var(--soft)"><span class="ms" style="font-size:26px">chevron_right</span></div>'
        step_html += f"""<div class="node" style="padding:20px 18px;flex:1 1 0">
      <span class="ms" style="font-size:30px;color:var(--indigo)">{icon}</span>
      <div style="font-size:19px;font-weight:700;letter-spacing:-0.01em;margin-top:10px">{title}</div>
      <div style="font-size:15px;color:var(--muted);line-height:1.45;margin-top:6px">{text}</div></div>"""
    out_html = "".join(
        f"""<div class="node" style="padding:20px 20px;{'border-color:var(--indigo-line);background:var(--indigo-soft)' if tinted else ''}">
      <div style="display:flex;align-items:center;gap:10px"><span class="ms" style="font-size:26px;color:var(--indigo)">{icon}</span>
      <div style="font-size:19px;font-weight:700;letter-spacing:-0.01em">{title}</div></div>
      <div style="font-size:15px;color:var(--muted);line-height:1.45;margin-top:8px">{text}</div></div>"""
        for icon, title, text, tinted in OUTPUTS
    )
    url = page("07-how-it-works", f"""<div class="canvas" style="width:1200px;height:800px;padding:48px 48px 0">
  {header("How it works", "Static and offline, with every result traceable",
          "Synthetic snapshots in, a verdict that points at JSON lines out. The only AWS call is the Bedrock explanation.")}
  <div style="position:absolute;left:48px;right:48px;top:200px">
    <div style="display:flex;gap:8px;align-items:stretch">{step_html}</div>
    <div style="margin:22px 0 0;display:flex;align-items:center;gap:12px;padding:14px 18px;border-radius:10px;
      background:var(--amber-soft);border:1px solid var(--amber-line);color:var(--amber-text);font-size:16px;font-weight:500">
      <span class="ms" style="font-size:22px">help</span>A missing fact is unknown, never safe: the result is marked incomplete, and the check fails.</div>
    <div style="display:flex;align-items:center;gap:12px;margin:26px 0 14px;color:var(--muted);font-size:15px;font-weight:600">
      <span class="ms" style="font-size:20px;color:var(--indigo)">call_split</span>One analysis, three outputs</div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">{out_html}</div>
  </div>
</div>""")
    jobs.append({"url": url, "out": str(devpost / "gallery" / "07-how-it-works.png"), "width": 1200, "height": 800, "scale": 2})
    return jobs


def visibly_changed(new: Path, old: Path) -> bool:
    """False only when old exists and matches new up to anti-aliasing noise."""
    if not old.exists():
        return True
    if new.suffix != ".png":
        return new.read_bytes() != old.read_bytes()
    a, b = Image.open(new).convert("RGBA"), Image.open(old).convert("RGBA")
    if a.size != b.size:
        return True
    # The largest difference across all four channels. getbbox() on an RGBA image would look at alpha only.
    largest = functools.reduce(ImageChops.lighter, ImageChops.difference(a, b).split())
    return largest.point(lambda v: 255 if v > NOISE else 0).getbbox() is not None


@functools.cache
def chrome() -> str:
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
    for candidate in (os.environ.get("CHROME"), MAC_CHROME, *map(shutil.which, names)):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("Google Chrome was not found; set CHROME to its path.")


@functools.cache
def node() -> str:
    path = shutil.which("node")
    version = subprocess.run([path, "--version"], capture_output=True, text=True).stdout.strip() if path else ""
    if not version.startswith("v") or int(version[1:].split(".")[0]) < 22:
        sys.exit(f"Node 22 or newer is needed for its built-in WebSocket; found {version or 'no node'}.")
    return path


def render(jobs: list[dict], work: Path, name: str) -> None:
    path = work / f"{name}.json"
    path.write_text(json.dumps(jobs), encoding="utf-8")
    subprocess.run([node(), str(SHOOT), str(path)], check=True, env={**os.environ, "CHROME": chrome()})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="replace every file, not only the visibly changed ones")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="attackgraph-assets-") as tmp:
        work = Path(tmp)
        shots, out = work / "shots", work / "out"
        render(shot_jobs(shots), work, "shots")
        render(asset_jobs(work / "pages", shots, out), work, "assets")
        outputs = {path: ROOT / path.relative_to(out) for path in out.rglob("*") if path.is_file()}
        outputs.update({shots / f"{name}.png": ROOT / "docs" / "images" / file for name, file in README_SHOTS.items()})
        replaced = []
        for new, old in sorted(outputs.items(), key=lambda item: item[1]):
            if args.force or visibly_changed(new, old):
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(new, old)
                replaced.append(old.relative_to(ROOT).as_posix())
    print(f"Rendered {len(outputs)} files; replaced {len(replaced)}" + (":" if replaced else "."))
    for path in replaced:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
