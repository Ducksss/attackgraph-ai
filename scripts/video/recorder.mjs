// Frame-by-frame recorder: a virtual camera over a page, captured with Page.captureScreenshot
// and piped into ffmpeg as a 30 fps intermediate clip. Nothing here depends on wall-clock
// time: every scroll, zoom and cursor move is computed per frame, and CSS animations are
// paused and stepped to the frame's time, so a re-shoot gives the same motion.
import { spawn } from "node:child_process";
import { readFileSync, renameSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { SCRIPT_DIR, sleep } from "./cdp.mjs";

export const FPS = 30;
export const VW = 1536; // CSS viewport
export const VH = 864;
export const DSF = 1.25; // 1536 x 864 CSS at 1.25 = 1920 x 1080
export const OUT_W = 1920;
export const OUT_H = 1080;
export const CAPTIONS = JSON.parse(readFileSync(join(SCRIPT_DIR, "captions.json"), "utf8"));
export const FFMPEG = process.env.FFMPEG || "ffmpeg"; // from PATH unless FFMPEG names the binary

export const wordCount = (text) => text.trim().split(/\s+/).length;
// Rules: every caption on screen for at least 2.5 s and at no more than 3 words per second.
export const minSeconds = (text) => Math.max(2.5, wordCount(text) / 3);
const CAPTION_PAD = 0.35; // reading slack beyond the minimum

export const easeInOut = (t) => -(Math.cos(Math.PI * t) - 1) / 2;

// Injected into every page: sets the scroll position, steps animations to the frame time,
// and draws a cursor (the headless browser has none).
const PAGE_HELPER = String.raw`(() => {
  if (window.__ag) return true;
  const NS = 'http://www.w3.org/2000/svg';
  const cursor = document.createElement('div');
  cursor.setAttribute('data-ag-overlay', 'cursor');
  cursor.innerHTML = '<svg xmlns="' + NS + '" width="30" height="30" viewBox="0 0 30 30"><path d="M4 3 L4 23.5 L9.2 18.6 L12.6 26.4 L16.3 24.8 L12.9 17.1 L20 17.1 Z" fill="#111114" stroke="#ffffff" stroke-width="1.8" stroke-linejoin="round"/></svg>';
  Object.assign(cursor.style, { position: 'fixed', left: '0px', top: '0px', width: '30px', height: '30px', zIndex: '2147483647', pointerEvents: 'none', display: 'none', transformOrigin: '4px 3px', filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.35))' });
  const ring = document.createElement('div');
  ring.setAttribute('data-ag-overlay', 'ring');
  Object.assign(ring.style, { position: 'fixed', left: '0px', top: '0px', width: '0px', height: '0px', borderRadius: '50%', zIndex: '2147483646', pointerEvents: 'none', display: 'none', background: 'rgba(99,102,241,0.22)', border: '2px solid rgba(99,102,241,0.85)', boxSizing: 'border-box' });
  document.documentElement.append(ring, cursor);
  const scroller = (sel) => (sel ? document.querySelector(sel) : null);
  const infinite = (a) => { try { return a.effect && a.effect.getComputedTiming().endTime === Infinity; } catch (e) { return false; } };
  window.__ag = {
    frame(s) {
      const el = scroller(s.scroller);
      if (s.scroll != null) {
        if (el) el.scrollTop = s.scroll;
        else window.scrollTo({ top: s.scroll, left: 0, behavior: 'instant' });
      }
      for (const a of document.getAnimations()) {
        try {
          if (infinite(a)) { if (a.playState !== 'paused') a.pause(); a.currentTime = s.t; }
          else if (a.playState !== 'finished') a.finish();
        } catch (e) {}
      }
      const c = s.cursor || {};
      if (c.visible) {
        cursor.style.display = 'block';
        cursor.style.opacity = String(c.opacity == null ? 1 : c.opacity);
        cursor.style.transform = 'translate(' + (c.x - 4) + 'px,' + (c.y - 3) + 'px) scale(' + (c.scale || 1) + ')';
      } else cursor.style.display = 'none';
      if (c.ring) {
        const r = c.ring.r;
        ring.style.display = 'block';
        ring.style.width = ring.style.height = (2 * r) + 'px';
        ring.style.transform = 'translate(' + (c.ring.x - r) + 'px,' + (c.ring.y - r) + 'px)';
        ring.style.opacity = String(c.ring.o);
      } else ring.style.display = 'none';
      return new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(() => res({ scroll: el ? el.scrollTop : window.scrollY }))));
    },
    // Is an endlessly running animation visible inside this viewport rectangle?
    animating(rect) {
      return document.getAnimations().some((a) => {
        if (!infinite(a)) return false;
        const t = a.effect.target;
        if (!t || !t.getBoundingClientRect) return false;
        if (t.checkVisibility && !t.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
        const r = t.getBoundingClientRect();
        if (r.width === 0 && r.height === 0) return false;
        return r.right > rect.x && r.left < rect.x + rect.w && r.bottom > rect.y && r.top < rect.y + rect.h;
      });
    },
  };
  return true;
})()`;

export class Recorder {
  // scroller: CSS selector of the scrolling element, or null for the window.
  constructor(page, { id, out, scroller = null, log = console.log }) {
    this.page = page;
    this.id = id;
    this.out = out;
    this.scroller = scroller;
    this.log = log;
    this.frames = 0;
    this.cues = [];
    this.open = null;
    this.cam = { x: 0, y: 0, w: VW };
    this.cur = { visible: false, x: VW / 2, y: VH / 2, opacity: 1, scale: 1, ring: null };
    this.lay = { max: 0, top: 0 };
    this.notes = [];
    this.last = null;
  }

  camH(w = this.cam.w) {
    return (w * VH) / VW;
  }

  async inject() {
    await this.page.evaluate(PAGE_HELPER);
  }

  async start() {
    await this.inject();
    await this.refresh();
    const part = `${this.out}.part.mp4`;
    rmSync(part, { force: true });
    this.ff = spawn(
      FFMPEG,
      ["-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "-",
       "-vf", `scale=${OUT_W}:${OUT_H}:flags=lanczos,format=yuv444p`, "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
       "-g", "60", "-r", String(FPS), part],
      { stdio: ["pipe", "inherit", "inherit"] },
    );
    this.ffDone = new Promise((resolve, reject) => {
      this.ff.on("error", (e) => reject(new Error(`ffmpeg did not start (${FFMPEG}): ${e.message}`)));
      this.ff.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg exited ${code}`))));
    });
  }

  // Scroll range and the scroller's viewport offset; call again after the page's height changes.
  async refresh() {
    const sel = this.scroller ? `document.querySelector(${JSON.stringify(this.scroller)})` : "null";
    this.lay = await this.page.evaluate(`(() => { const el = ${sel};
      return el ? { max: el.scrollHeight - el.clientHeight, top: el.getBoundingClientRect().top, scroll: el.scrollTop }
                : { max: document.documentElement.scrollHeight - innerHeight, top: 0, scroll: scrollY }; })()`);
    return this.lay;
  }

  clampCam(c) {
    const w = Math.min(VW, Math.max(320, c.w));
    const h = this.camH(w);
    const x = Math.min(VW - w, Math.max(0, c.x));
    const y = Math.min(this.lay.max + VH - h, Math.max(0, c.y));
    return { x, y, w };
  }

  scrollFor(cam) {
    const h = this.camH(cam.w);
    let s = cam.y - (VH - h) / 2;
    s = Math.max(0, Math.min(this.lay.max, s));
    if (cam.y < s) s = cam.y;
    if (cam.y + h > s + VH) s = cam.y + h - VH;
    return Math.round(s); // Chrome keeps scroll offsets in whole CSS pixels
  }

  cursorState() {
    const c = this.cur;
    return { visible: c.visible, x: c.x, y: c.y, opacity: c.opacity, scale: c.scale, ring: c.ring };
  }

  async write(buf, n = 1) {
    for (let i = 0; i < n; i++) {
      if (!this.ff.stdin.write(buf)) await new Promise((r) => this.ff.stdin.once("drain", r));
      this.frames++;
    }
    this.last = buf;
  }

  // Render the page as the camera sees it and append one frame.
  async frame() {
    this.cam = this.clampCam(this.cam);
    const scroll = this.scrollFor(this.cam);
    const state = { scroller: this.scroller, scroll, t: (this.frames * 1000) / FPS, cursor: this.cursorState() };
    let res;
    try {
      res = await this.page.evaluate(`window.__ag.frame(${JSON.stringify(state)})`);
    } catch (e) {
      // The page replaced its document (a navigation or full re-render): reinstall the helper once.
      await this.inject();
      res = await this.page.evaluate(`window.__ag.frame(${JSON.stringify(state)})`);
    }
    const h = this.camH(this.cam.w);
    const actual = res.scroll;
    // The camera's top in viewport pixels, kept inside the viewport (scroll offsets are whole pixels,
    // so a full-height camera snaps to them; a zoomed one keeps its sub-pixel position).
    const want = this.cam.y - actual + (this.scroller ? this.lay.top : 0);
    const vy = Math.min(VH - h, Math.max(0, want));
    if (Math.abs(vy - want) > 1.01) this.notes.push(`frame ${this.frames}: camera clamped by ${(want - vy).toFixed(1)} px`);
    const clip = { x: this.cam.x, y: this.scroller ? vy : vy + actual, width: this.cam.w, height: h, scale: VW / this.cam.w };
    const buf = await this.page.screenshot({ format: "png", clip });
    await this.write(buf);
  }

  async animatingInView() {
    const h = this.camH();
    const top = this.scroller ? this.cam.y - this.scrollFor(this.cam) + this.lay.top : this.cam.y - this.scrollFor(this.cam);
    return this.page.evaluate(`window.__ag.animating(${JSON.stringify({ x: this.cam.x, y: top, w: this.cam.w, h })})`);
  }

  // Hold still. Frames are duplicated unless an animation is running in view (live: 'auto').
  async hold(sec, { live = "auto" } = {}) {
    const n = Math.round(sec * FPS);
    if (n <= 0) return;
    const isLive = live === "auto" ? await this.animatingInView() : live;
    if (isLive) {
      for (let i = 0; i < n; i++) await this.frame();
    } else {
      await this.frame();
      if (n > 1) await this.write(this.last, n - 1);
    }
  }

  // Move the camera (content coordinates; w < 1536 zooms in) with an ease-in-out.
  async move(target, sec) {
    await this.refresh();
    const from = { ...this.cam };
    const to = this.clampCam({ x: target.x ?? from.x, y: target.y ?? from.y, w: target.w ?? from.w });
    const n = Math.max(1, Math.round(sec * FPS));
    for (let i = 1; i <= n; i++) {
      const k = easeInOut(i / n);
      const w = Math.exp(Math.log(from.w) + (Math.log(to.w) - Math.log(from.w)) * k);
      this.cam = { x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k, w };
      await this.frame();
    }
    this.cam = to;
  }

  // A camera framing the union of boxes as large as it fits, with the caption band (the bottom
  // `reserve` of the frame) kept clear. Zoom is capped at maxZoom; boxes too tall for the frame
  // get a full-width camera aligned to their top.
  // align: 'top' puts the boxes at the top of the frame; 'center' centres them above the band;
  // 'bottom' sits them right on the band, so what the caption covers is the gap below them.
  fit(boxes, { margin = 24, reserve = 0.17, maxZoom = 1.42, align = "top" } = {}) {
    const bs = [].concat(boxes);
    const x0 = Math.min(...bs.map((b) => b.x)), y0 = Math.min(...bs.map((b) => b.y));
    const x1 = Math.max(...bs.map((b) => b.x + b.w)), y1 = Math.max(...bs.map((b) => b.y + b.h));
    const wH = x1 - x0 + 2 * margin;
    const wV = ((y1 - y0 + 2 * margin) / (1 - reserve)) * (VW / VH);
    const w = Math.min(VW, Math.max(wH, wV, VW / maxZoom));
    const usable = this.camH(w) * (1 - reserve);
    const y = align === "center" ? (y0 + y1) / 2 - usable / 2 : align === "bottom" ? y1 + margin - usable : y0 - margin;
    return { x: (x0 + x1) / 2 - w / 2, y, w };
  }

  // Content-coordinate box of the first visible element matching a selector, or {text} / {text, within}.
  async box(target) {
    const sel = this.scroller ? `document.querySelector(${JSON.stringify(this.scroller)})` : "null";
    const find = typeof target === "string" ? `document.querySelector(${JSON.stringify(target)})` : findByText(target);
    const r = await this.page.evaluate(`(() => { const el = ${find}; if (!el) return null; const sc = ${sel};
      const b = el.getBoundingClientRect(); const off = sc ? sc.scrollTop - sc.getBoundingClientRect().top : scrollY;
      return { x: b.left, y: b.top + off, w: b.width, h: b.height, vx: b.left, vy: b.top }; })()`);
    if (!r) throw new Error(`${this.id}: element not found: ${JSON.stringify(target)}`);
    return r;
  }

  // Viewport position of a content point under the current camera.
  toViewport(x, y) {
    const scroll = this.scrollFor(this.cam);
    return { x, y: y - scroll + (this.scroller ? this.lay.top : 0) };
  }

  // Move a drawn cursor to the element, press it with real mouse events, wait (not recorded)
  // until `wait` holds, then carry on recording. The wait is the jump cut.
  // press: false rehearses the motion without sending the click (used for the live Bedrock button in --dry runs).
  async click(target, { approach = 0.8, from = null, wait = null, waitTimeout = 45000, anchor = null, during = 0, onClicked = null, press = true } = {}) {
    await this.refresh();
    const b = await this.box(target);
    const p = this.toViewport(b.x + b.w / 2, b.y + b.h / 2);
    const vis = this.camH();
    const camTop = this.cam.y - this.scrollFor(this.cam);
    if (p.y < camTop || p.y > camTop + vis || p.x < this.cam.x || p.x > this.cam.x + this.cam.w) {
      throw new Error(`${this.id}: click target outside the camera: ${JSON.stringify(target)}`);
    }
    const start = from ?? { x: p.x + 150, y: p.y + 105 };
    const n = Math.max(2, Math.round(approach * FPS));
    this.cur = { visible: true, x: start.x, y: start.y, opacity: 0, scale: 1, ring: null };
    for (let i = 1; i <= n; i++) {
      const k = easeInOut(i / n);
      this.cur.x = start.x + (p.x - start.x) * k;
      this.cur.y = start.y + (p.y - start.y) * k;
      this.cur.opacity = Math.min(1, i / 6);
      await this.page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: this.cur.x, y: this.cur.y });
      await this.frame();
    }
    for (let i = 0; i < 5; i++) await this.frame(); // settle on the target, hover state shown
    this.cur.scale = 0.86;
    this.cur.ring = { x: p.x, y: p.y, r: 7, o: 0.95 };
    for (let i = 0; i < 3; i++) await this.frame();
    const anchorBefore = anchor ? await this.box(anchor) : null;
    if (press) {
      await this.page.send("Input.dispatchMouseEvent", { type: "mousePressed", x: p.x, y: p.y, button: "left", clickCount: 1 });
      await this.page.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: p.x, y: p.y, button: "left", clickCount: 1 });
      if (onClicked) await onClicked();
    }
    // A few recorded frames of the in-between state (a spinner), if asked for.
    for (let i = 0; i < Math.round(during * FPS); i++) {
      if (wait && (await this.page.evaluate(wait).catch(() => false))) break;
      await this.frame();
    }
    if (wait) await this.page.waitFor(wait, { timeout: waitTimeout, label: `${this.id} wait after click` });
    await sleep(400);
    await this.inject();
    await this.refresh();
    if (anchor) {
      const after = await this.box(anchor);
      this.cam.y += after.y - anchorBefore.y;
    }
    // Release: the ring spreads and fades, then the cursor fades out.
    const m = Math.round(0.4 * FPS);
    for (let i = 1; i <= m; i++) {
      const k = i / m;
      this.cur.scale = 1;
      this.cur.ring = { x: p.x, y: p.y, r: 7 + 22 * easeInOut(k), o: 0.95 * (1 - k) };
      await this.frame();
    }
    this.cur.ring = null;
    const f = Math.round(0.35 * FPS);
    for (let i = 1; i <= f; i++) {
      this.cur.opacity = 1 - i / f;
      await this.frame();
    }
    this.cur.visible = false;
    await this.page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 2, y: VH - 2 });
    return p;
  }

  // Start a caption cue. The previous cue ends here, after padding to its minimum length.
  async say(id) {
    if (!(id in CAPTIONS)) throw new Error(`no caption ${id} in captions.json`);
    await this.endCaption();
    this.open = { id, start: this.frames, min: minSeconds(CAPTIONS[id]) + CAPTION_PAD };
  }

  async endCaption() {
    if (!this.open) return;
    const need = Math.ceil(this.open.min * FPS) - (this.frames - this.open.start);
    if (need > 0) await this.hold(need / FPS);
    this.cues.push({ id: this.open.id, start: this.open.start, end: this.frames });
    this.open = null;
  }

  async finish(meta = {}) {
    await this.endCaption();
    this.ff.stdin.end();
    await this.ffDone;
    renameSync(`${this.out}.part.mp4`, `${this.out}.mp4`);
    const manifest = {
      id: this.id,
      fps: FPS,
      frames: this.frames,
      seconds: this.frames / FPS,
      cues: this.cues,
      notes: this.notes,
      capturedAt: new Date().toISOString(),
      ...meta,
    };
    writeFileSync(`${this.out}.json`, JSON.stringify(manifest, null, 1));
    return manifest;
  }

  abort() {
    try {
      this.ff.stdin.destroy();
      this.ff.kill("SIGKILL");
    } catch {}
    rmSync(`${this.out}.part.mp4`, { force: true });
  }
}

// An element by its exact visible text: {text, tag?, within?}.
export function findByText({ text, tag = "*", within = null, nth = 0 }) {
  return `(() => { const root = ${within ? `document.querySelector(${JSON.stringify(within)})` : "document"};
    if (!root) return null;
    const all = [...root.querySelectorAll(${JSON.stringify(tag)})].filter((e) => e.offsetParent !== null || getComputedStyle(e).position === 'fixed');
    const hits = all.filter((e) => e.textContent.trim() === ${JSON.stringify(text)});
    const leaf = hits.filter((e) => !hits.some((o) => o !== e && e.contains(o)));
    return leaf[${nth}] || null; })()`;
}
