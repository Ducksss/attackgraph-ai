#!/usr/bin/env node
// One command for the whole cut. Run from anywhere; paths resolve from this file.
//
//   node scripts/video/make.mjs                re-assemble from the existing clips: captions, cards, the MP4, the SRT,
//                                              shots.md and the contact sheet
//   node scripts/video/make.mjs 3 9            re-shoot shots 3 and 9 (the hosted overview), then re-assemble
//   node scripts/video/make.mjs 0 10           re-render the title card (0) and the end card (10), then re-assemble
//   node scripts/video/make.mjs all            re-shoot every shot except 7 (the live Bedrock take), then re-assemble
//   node scripts/video/make.mjs 7 --live       re-shoot 7 with one live Bedrock press (budget: 3 presses in total)
//   node scripts/video/make.mjs 7 --recorded   shot 7 from the hosted demo's recorded AI reply instead
//   node scripts/video/make.mjs 7 --dry        rehearse shot 7 without pressing the button (writes clips/dry-07.mp4 only)
//   --out DIR                                  write everything under DIR instead of build/video/
//   --no-assemble                              shoot only;  --cards  re-render the title and end cards
//
// Shots 4 to 8 need the local app (APP_URL, default http://127.0.0.1:8599); see README.md.
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { findChrome, launchBrowser, REPO_ROOT, SCRIPT_DIR, sleep } from "./cdp.mjs";
import { CAPTIONS, DSF, FFMPEG, FPS, minSeconds, OUT_H, OUT_W, Recorder, VH, VW, wordCount } from "./recorder.mjs";
import { PRESS_BUDGET, pressCount, SHOTS } from "./shots.mjs";

function fail(message) {
  console.error(`make.mjs: ${message}`);
  process.exit(1);
}

// ---------- preflight: Node, arguments, tools ----------

const [nodeMajor] = process.versions.node.split(".").map(Number);
if (nodeMajor < 22 || typeof WebSocket !== "function") fail(`Node 22 or later is needed for its built-in WebSocket (this is ${process.version}).`);

const KNOWN_FLAGS = new Set(["live", "recorded", "dry", "no-assemble", "cards"]);
const args = process.argv.slice(2);
const flags = new Set();
const requested = [];
let outArg = null;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === "--out" || a.startsWith("--out=")) {
    outArg = a === "--out" ? args[++i] : a.slice("--out=".length);
    if (!outArg || outArg.startsWith("--")) fail("--out needs a directory");
  } else if (a.startsWith("--")) {
    if (!KNOWN_FLAGS.has(a.slice(2))) fail(`unknown option ${a}`);
    flags.add(a.slice(2));
  } else requested.push(a);
}

const OUT = outArg ? resolve(outArg) : join(REPO_ROOT, "build", "video");
const CLIPS = join(OUT, "clips");
const CAPDIR = join(OUT, "captions");
const CARD_PNGS = join(OUT, "cards");
const LOGS = join(OUT, "logs");
const OUTPUT = join(OUT, "attackgraph-ai-demo.mp4");
const SRT = join(OUT, "attackgraph-ai-demo.srt");
const CARD_TEMPLATES = join(SCRIPT_DIR, "cards"); // HTML only; they read the mark from docs/brand/
const ORDER = ["title", 1, 2, 3, 4, 5, 6, 7, 8, 9, "end"];
const CARD_SECONDS = { title: 4.0, end: 8.0 };
const CARD_TARGETS = { 0: "title", title: "title", 10: "end", end: "end" };
const STRIP_H = 240; // caption strips are 1920 x 240, laid over the bottom of the frame
const pad2 = (n) => String(n).padStart(2, "0");
const FFPROBE = process.env.FFPROBE || (process.env.FFMPEG && /[\\/]/.test(FFMPEG) ? join(dirname(FFMPEG), "ffprobe") : "ffprobe");

// "all" is every shot except 7, whose live take needs --live; it can sit beside other targets ("all 7 --recorded").
const targets = [...new Set(requested.flatMap((t) => (t === "all" ? Object.keys(SHOTS).filter((k) => k !== "7" && k !== "7r") : [t])))];
const cardTargets = targets.filter((t) => t in CARD_TARGETS).map((t) => CARD_TARGETS[t]);
const shotTargets = targets.filter((t) => !(t in CARD_TARGETS));
for (const t of shotTargets) if (!SHOTS[t]) fail(`no shot ${t}: shots are 1 to 9, 0 and 10 are the title and end cards, or all`);

function checkTools() {
  try {
    findChrome();
  } catch (e) {
    fail(e.message);
  }
  const enc = spawnSync(FFMPEG, ["-hide_banner", "-encoders"], { encoding: "utf8" });
  if (enc.error) fail(`ffmpeg not found (${FFMPEG}): install it, or set FFMPEG to its binary.`);
  if (!/\blibx264\b/.test(enc.stdout)) fail(`${FFMPEG} has no libx264 encoder: use an ffmpeg built with libx264 (libass and freetype are not needed).`);
  const probe = spawnSync(FFPROBE, ["-version"], { encoding: "utf8" });
  if (probe.error) fail(`ffprobe not found (${FFPROBE}): it ships with ffmpeg; or set FFPROBE to its binary.`);
}
checkTools();

function run(cmd, argv) {
  const r = spawnSync(cmd, argv, { stdio: ["ignore", "inherit", "inherit"] });
  if (r.status !== 0) throw new Error(`${cmd} failed (${r.status ?? r.error?.message})`);
}
function probeSeconds(file) {
  const r = spawnSync(FFPROBE, ["-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", file], { encoding: "utf8" });
  return Number(r.stdout.trim()) / FPS;
}
const fmt = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
const srtTime = (s) => {
  const ms = Math.round(s * 1000);
  const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), sec = Math.floor((ms % 60000) / 1000), r = ms % 1000;
  return `${pad2(h)}:${pad2(m)}:${pad2(sec)},${String(r).padStart(3, "0")}`;
};
const fileUrl = (file) => pathToFileURL(file).href;

async function shoot(key) {
  const shot = SHOTS[key];
  if (!shot) throw new Error(`no shot ${key}`);
  if (key === "7" && flags.has("recorded")) return shoot("7r");
  const slot = shot.slot ?? Number(key);
  if (shot.live && !flags.has("dry")) {
    if (!flags.has("live")) throw new Error("shot 7 presses Explain with Amazon Bedrock: pass --live (or --dry / --recorded)");
    const used = pressCount(LOGS);
    if (used >= PRESS_BUDGET) throw new Error(`Bedrock press budget used (${used}/${PRESS_BUDGET}, ${join(LOGS, "bedrock-presses.jsonl")}); use --recorded`);
    console.log(`shot 7: live press ${used + 1} of ${PRESS_BUDGET}`);
  }
  mkdirSync(CLIPS, { recursive: true });
  const out = join(CLIPS, flags.has("dry") && shot.live ? `dry-${pad2(slot)}` : pad2(slot));
  const t0 = Date.now();
  const browser = await launchBrowser();
  try {
    const page = await browser.newPage({ width: VW, height: VH, scale: DSF });
    await page.goto(shot.url);
    await shot.prepare(page);
    const rec = new Recorder(page, { id: `shot ${key}`, out, scroller: shot.scroller ?? null });
    await rec.start();
    let extra;
    try {
      extra = await shot.run(rec, { dry: flags.has("dry"), logs: LOGS });
    } catch (e) {
      rec.abort();
      throw e;
    }
    const m = await rec.finish({ key: String(key), slot, slug: shot.slug, source: shot.source, url: shot.url, what: shot.what,
      hostedOverview: Boolean(shot.hostedOverview), dry: flags.has("dry"), ...(extra ?? {}) });
    if (shot.live && !flags.has("dry")) copyFileSync(`${out}.mp4`, join(CLIPS, `07-live-take-${Date.now()}.mp4`));
    if (page.consoleErrors.length) console.log(`  page errors: ${page.consoleErrors.slice(0, 3).join(" | ")}`);
    console.log(`shot ${key}: ${m.frames} frames, ${m.seconds.toFixed(2)} s, ${m.cues.length} captions (${((Date.now() - t0) / 1000).toFixed(0)} s to shoot)`);
    for (const n of m.notes) console.log(`  note: ${n}`);
  } finally {
    await browser.close();
  }
}

// ---------- captions and cards (rendered in Chrome, so ffmpeg needs no drawtext or libass) ----------

const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function captionHtml(text) {
  return `<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@500&display=swap">
<style>
html,body{margin:0;width:${OUT_W}px;height:${STRIP_H}px;background:transparent;overflow:hidden}
.cap{position:absolute;left:50%;bottom:50px;transform:translateX(-50%);box-sizing:border-box;max-width:1560px;width:max-content;
 padding:13px 32px 15px;border-radius:16px;background:rgba(15,15,25,0.8);color:#fff;text-align:center;
 font:500 42px/1.3 Inter,"Helvetica Neue",Helvetica,Arial,sans-serif;letter-spacing:-0.005em;text-wrap:balance;
 -webkit-font-smoothing:antialiased}
</style></head><body><div class="cap" id="c">${esc(text)}</div></body></html>`;
}

async function renderCaptions(ids) {
  mkdirSync(CAPDIR, { recursive: true });
  const browser = await launchBrowser();
  const problems = [];
  try {
    const page = await browser.newPage({ width: OUT_W, height: STRIP_H, scale: 1, transparent: true });
    for (const id of ids) {
      const file = join(CAPDIR, `${id}.html`);
      writeFileSync(file, captionHtml(CAPTIONS[id]));
      await page.goto(fileUrl(file));
      await page.evaluate("document.fonts.ready.then(() => true)");
      // Size the box to its balanced lines (a wrapped block otherwise keeps its full max-width).
      const lines = await page.evaluate(`(() => { const el = document.getElementById('c'); const r = document.createRange(); r.selectNodeContents(el);
        const rects = [...r.getClientRects()]; const n = new Set(rects.map((q) => Math.round(q.top))).size;
        if (n > 1) { const w = Math.max(...rects.map((q) => q.right)) - Math.min(...rects.map((q) => q.left)); el.style.width = Math.ceil(w + 64 + 4) + 'px'; }
        const again = new Set([...r.getClientRects()].map((q) => Math.round(q.top))).size; return again; })()`);
      const font = await page.evaluate("document.fonts.check('500 42px Inter')");
      if (lines > 2) problems.push(`${id}: ${lines} lines`);
      if (!font) problems.push(`${id}: Inter not loaded (captions load it from Google Fonts)`);
      writeFileSync(join(CAPDIR, `${id}.png`), await page.screenshot({ format: "png" }));
    }
  } finally {
    await browser.close();
  }
  if (problems.length) throw new Error("caption problems: " + problems.join("; "));
}

async function renderCards(names) {
  mkdirSync(CARD_PNGS, { recursive: true });
  mkdirSync(CLIPS, { recursive: true });
  const browser = await launchBrowser();
  try {
    const page = await browser.newPage({ width: OUT_W, height: OUT_H, scale: 1 });
    for (const name of names) {
      await page.goto(fileUrl(join(CARD_TEMPLATES, `${name}.html`)));
      await page.evaluate("document.fonts.ready.then(() => true)");
      await page.waitFor("[...document.images].every((i) => i.complete && i.naturalWidth > 0)", { timeout: 10000, label: `${name} card: the mark from docs/brand/mark.svg did not load` });
      await sleep(300);
      writeFileSync(join(CARD_PNGS, `${name}.png`), await page.screenshot({ format: "png" }));
    }
  } finally {
    await browser.close();
  }
  for (const name of names) {
    const d = CARD_SECONDS[name];
    const fade = name === "title" ? `fade=t=in:st=0:d=0.5` : `fade=t=in:st=0:d=0.35,fade=t=out:st=${(d - 0.8).toFixed(2)}:d=0.8`;
    run(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", String(FPS), "-t", String(d), "-i", join(CARD_PNGS, `${name}.png`),
      "-vf", `${fade},format=yuv444p`, "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-r", String(FPS), join(CLIPS, `${name}.mp4`)]);
    console.log(`card ${name}: ${d.toFixed(1)} s`);
  }
}

// ---------- assembly ----------

function loadTimeline() {
  let t = 0;
  const items = [];
  for (const key of ORDER) {
    if (typeof key === "string") {
      const file = join(CLIPS, `${key}.mp4`);
      const seconds = probeSeconds(file);
      items.push({ key, file, seconds, start: t, cues: [], source: key === "title" ? "Title card" : "End card", what: key === "title" ? "Logo, name and one-line description" : "Links, technologies, synthetic data only, visual style credit" });
      t += seconds;
      continue;
    }
    const base = join(CLIPS, pad2(key));
    if (!existsSync(`${base}.mp4`)) throw new Error(`missing clip for shot ${key}: run node scripts/video/make.mjs ${key}${key === 7 ? " --recorded (or --live)" : ""}`);
    const m = JSON.parse(readFileSync(`${base}.json`, "utf8"));
    const seconds = m.frames / FPS;
    items.push({ ...m, key, file: `${base}.mp4`, seconds, start: t, cues: m.cues.map((c) => ({ ...c, text: CAPTIONS[c.id] })) });
    t += seconds;
  }
  return { items, total: t };
}

function checkCaptions(items) {
  const warnings = [];
  for (const it of items)
    for (const c of it.cues) {
      const d = (c.end - c.start) / FPS;
      const w = wordCount(c.text);
      if (w > 14) warnings.push(`${c.id}: ${w} words (max ~14)`);
      if (d + 1e-6 < minSeconds(c.text)) warnings.push(`${c.id}: ${d.toFixed(2)} s on screen, needs ${minSeconds(c.text).toFixed(2)} s (re-shoot shot ${it.key})`);
      if (w / d > 3.0001) warnings.push(`${c.id}: ${(w / d).toFixed(2)} words/s`);
    }
  return warnings;
}

function assemble(items, total) {
  const inputs = [];
  const filters = [];
  const labels = [];
  let n = 0;
  for (const it of items) {
    inputs.push("-i", it.file);
    const vi = n++;
    let cur = `v${vi}`;
    filters.push(`[${vi}:v]setpts=PTS-STARTPTS,fps=${FPS},scale=${OUT_W}:${OUT_H},setsar=1,format=yuv444p[${cur}]`);
    it.cues.forEach((c, j) => {
      const s = c.start / FPS, e = c.end / FPS;
      inputs.push("-loop", "1", "-framerate", String(FPS), "-t", it.seconds.toFixed(3), "-i", join(CAPDIR, `${c.id}.png`));
      const ci = n++;
      const f = Math.min(0.18, (e - s) / 4);
      filters.push(`[${ci}:v]format=rgba,fade=t=in:st=${s.toFixed(3)}:d=${f.toFixed(3)}:alpha=1,fade=t=out:st=${(e - f).toFixed(3)}:d=${f.toFixed(3)}:alpha=1[c${ci}]`);
      const next = `v${vi}_${j}`;
      filters.push(`[${cur}][c${ci}]overlay=0:${OUT_H - STRIP_H}:enable='between(t,${s.toFixed(3)},${e.toFixed(3)})':eof_action=pass:shortest=1:format=yuv444[${next}]`);
      cur = next;
    });
    labels.push(`[${cur}]`);
  }
  filters.push(`${labels.join("")}concat=n=${labels.length}:v=1:a=0,format=yuv420p[vout]`);
  const script = join(LOGS, "filtergraph.txt");
  mkdirSync(LOGS, { recursive: true });
  writeFileSync(script, filters.join(";\n"));
  run(FFMPEG, ["-hide_banner", "-loglevel", "error", "-stats", "-y", ...inputs,
    "-f", "lavfi", "-t", total.toFixed(3), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    "-filter_complex_script", script, "-map", "[vout]", "-map", `${n}:a`,
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", String(FPS),
    "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", OUTPUT]);
}

function writeSrt(items) {
  const lines = [];
  let i = 1;
  for (const it of items)
    for (const c of it.cues) {
      lines.push(String(i++), `${srtTime(it.start + c.start / FPS)} --> ${srtTime(it.start + c.end / FPS - 0.04)}`, c.text, "");
    }
  writeFileSync(SRT, lines.join("\n"));
}

function srcTag(it) {
  if (typeof it.key === "string") return "Card";
  if (/^GitHub/.test(it.source)) return "GitHub";
  if (/^Local/.test(it.source)) return "Local";
  return "Hosted";
}

function liveNote(items) {
  const s7 = items.find((it) => it.key === 7);
  if (!s7) return "";
  if (s7.variant !== "live") return `- Shot 7 uses the hosted demo's recorded AI reply (${s7.variant}), shown with its date and request ID.`;
  const r = s7.reply || {};
  return `- Shot 7 is a live take: one Converse call to ${r.model ?? "Amazon Nova Pro"} in ${r.region ?? "ap-southeast-1"}, prompt ${r.prompt ?? "?"}, request ${r.request ?? "?"} (${r.tokens ?? "?"}, ${r.latency ?? "?"}), press ${r.press ?? "?"} of ${PRESS_BUDGET}. Every press is logged in \`logs/bedrock-presses.jsonl\` and every reply in \`logs/bedrock-reply-*.json\`; earlier takes are kept as \`clips/07-live-take-*.mp4\`. \`--recorded\` uses the hosted demo's recorded reply instead.`;
}

function writeShotsMd(items, total) {
  const rows = items.map((it, idx) => {
    const num = it.key === "title" ? "0 (title)" : it.key === "end" ? "10 (end card)" : String(it.key);
    const caps = it.cues.length ? it.cues.map((c) => `${fmt(it.start + c.start / FPS)} "${c.text}"`).join("<br>") : "(no caption; the card's own text)";
    const src = `${srcTag(it)}${it.url ? `: ${it.url}` : ""}${it.variant ? ` (${it.variant} AI reply)` : ""}`;
    return `| ${num} | ${fmt(it.start)}–${fmt(it.start + it.seconds)} | ${src} | ${it.what ?? ""} | ${caps} | ${it.hostedOverview ? "yes" : ""} |`;
  });
  const overview = items.filter((it) => it.hostedOverview).map((it) => `shot ${it.key} (${it.slug})`).join(" and ");
  const captured = items.filter((it) => it.capturedAt).map((it) => `shot ${it.key} ${it.capturedAt.slice(0, 16).replace("T", " ")}`).join(", ");
  const md = `# AttackGraph AI demo video: shot list

Cut: \`attackgraph-ai-demo.mp4\`, ${fmt(total)} (${total.toFixed(1)} s), 1920x1080, 30 fps, H.264 + silent AAC. Captions are burned in and also in \`attackgraph-ai-demo.srt\`.
Assembled ${new Date().toISOString()}.

| Shot | Time | Source | On screen | Captions (start time and text) | Hosted overview |
|---|---|---|---|---|---|
${rows.join("\n")}

**From the hosted site's overview:** ${overview || "none"}. These are the shots to re-shoot after the overview is redeployed: \`node scripts/video/make.mjs 3 9\`.

## Notes

- Captured (UTC): ${captured}.
${liveNote(items)}
- GitHub shots run in a fresh signed-out Chrome profile; avatars are hidden with CSS so nothing personal is on screen.
- GitHub, signed out: while PR #3 has two failing runs of the check, Files changed shows its note on line 27 twice. The Checks tab does not expand its annotations signed out, so shot 2 uses the latest run's summary page, which shows the failed AttackGraph AI job and the note's title "New path to a protected role".
- Streamlit's hover tooltips are hidden with CSS during capture (the drawn cursor dwells on buttons while frames are captured).
- Captions: at most 14 words, at least 2.5 s on screen, at most 3 words per second; make.mjs checks all three on every assembly.
- How to rebuild: \`scripts/video/README.md\`.
`;
  writeFileSync(join(OUT, "shots.md"), md);
}

async function contactSheet(items) {
  const dir = join(LOGS, "thumbs");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  const tiles = [];
  for (const it of items) {
    // A representative frame: inside the shot's last caption, or the middle of a card.
    const last = it.cues[it.cues.length - 1];
    const t = last ? it.start + (last.start + (last.end - last.start) * 0.5) / FPS : it.start + it.seconds * 0.6;
    const file = join(dir, `${String(it.key)}.png`);
    run(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", "-ss", t.toFixed(3), "-i", OUTPUT, "-frames:v", "1", "-vf", "scale=640:360:flags=lanczos", file]);
    const num = it.key === "title" ? "Title" : it.key === "end" ? "10 · End card" : `Shot ${it.key}`;
    tiles.push({ file, label: num, sub: `${fmt(it.start)}–${fmt(it.start + it.seconds)} · ${srcTag(it)}${it.variant ? ` (${it.variant} AI)` : ""}`, note: it.what ?? "" });
  }
  const html = `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>body{margin:0;background:#f4f4f6;font-family:Inter,Helvetica,sans-serif;color:#111114}
h1{font-size:26px;margin:28px 32px 4px}p.s{margin:0 32px 18px;color:#5f5f72;font-size:15px}
.g{display:grid;grid-template-columns:repeat(4,640px);gap:22px;padding:0 32px 32px}
.t{background:#fff;border:1px solid #e2e2e8;border-radius:12px;overflow:hidden}.t img{display:block;width:640px;height:360px}
.l{padding:10px 14px 12px}.l b{font-size:17px}.l span{color:#5f5f72;font-size:14px;margin-left:8px}.l div{font-size:13px;color:#3a3a44;margin-top:4px;line-height:1.35}</style></head>
<body><h1>AttackGraph AI demo: contact sheet</h1><p class="s">One frame per shot from attackgraph-ai-demo.mp4 (${fmt(items.reduce((a, b) => a + b.seconds, 0))}), taken during each shot's last caption.</p><div class="g">
${tiles.map((t) => `<div class="t"><img src="${fileUrl(t.file)}"><div class="l"><b>${esc(t.label)}</b><span>${esc(t.sub)}</span><div>${esc(t.note)}</div></div></div>`).join("\n")}
</div></body></html>`;
  const file = join(dir, "sheet.html");
  writeFileSync(file, html);
  const browser = await launchBrowser();
  try {
    const page = await browser.newPage({ width: 32 * 2 + 640 * 4 + 22 * 3, height: 900, scale: 1 });
    await page.goto(fileUrl(file));
    await page.evaluate("document.fonts.ready.then(() => true)");
    await sleep(500);
    const h = await page.evaluate("document.documentElement.scrollHeight");
    const w = 32 * 2 + 640 * 4 + 22 * 3;
    writeFileSync(join(OUT, "contact-sheet.png"), await page.screenshot({ format: "png", clip: { x: 0, y: 0, width: w, height: h, scale: 1 }, beyond: true }));
  } finally {
    await browser.close();
  }
}

// ---------- main ----------

try {
  console.log(`output: ${OUT}`);
  for (const key of shotTargets) await shoot(key);
  const cards = new Set(flags.has("cards") ? ["title", "end"] : cardTargets);
  if (cards.size) await renderCards([...cards]);
  if (!flags.has("no-assemble") && !(flags.has("dry") && targets.length)) {
    mkdirSync(CLIPS, { recursive: true });
    const missing = ["title", "end"].filter((name) => !existsSync(join(CLIPS, `${name}.mp4`)));
    if (missing.length) await renderCards(missing);
    const { items, total } = loadTimeline();
    const ids = [...new Set(items.flatMap((it) => it.cues.map((c) => c.id)))];
    await renderCaptions(ids);
    const warnings = checkCaptions(items);
    for (const w of warnings) console.log(`caption warning: ${w}`);
    if (!warnings.length) console.log(`captions: all ${items.reduce((a, it) => a + it.cues.length, 0)} pass (at most 14 words, at least 2.5 s on screen, at most 3 words per second, at most 2 lines)`);
    assemble(items, total);
    writeSrt(items);
    writeShotsMd(items, total);
    await contactSheet(items);
    const size = statSync(OUTPUT).size / 1e6;
    console.log(`\n${OUTPUT}\n${fmt(total)} (${total.toFixed(2)} s), ${size.toFixed(1)} MB, ${items.reduce((a, it) => a + it.cues.length, 0)} captions`);
    if (total < 140 || total > 170) console.log(`length warning: ${total.toFixed(1)} s is outside 2:20-2:50`);
  }
} catch (e) {
  // A shot or tool failure: say what failed without a stack trace (set DEBUG=1 for one).
  fail(process.env.DEBUG ? e.stack : e.message);
}
