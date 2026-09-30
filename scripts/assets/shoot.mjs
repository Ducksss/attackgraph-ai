// Render pages to PNG with headless Chrome over the DevTools protocol, using no npm packages.
// scripts/build_assets.py drives it. It needs Node 22 or newer, for the built-in WebSocket, and
// Chrome at $CHROME (default: the macOS install path).
//
// usage: node scripts/assets/shoot.mjs jobs.json
// job: {url, out, width, height, scale = 2, transparent = false, js?, selector?, pad = 0, full = false, wait = 500}
// selector may be a list, which crops to the union of the elements' boxes.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const profile = mkdtempSync(join(tmpdir(), "attackgraph-chrome-"));
const chrome = spawn(
  CHROME,
  ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--hide-scrollbars",
   "--no-first-run", "--no-default-browser-check", "--font-render-hinting=none", "about:blank"],
  { stdio: ["ignore", "ignore", "pipe"] },
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ws;
try {
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = "";
    chrome.on("error", reject);
    chrome.stderr.on("data", (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) resolve(m[1]);
    });
    setTimeout(() => reject(new Error("Chrome did not start:\n" + buf)), 20000);
  });

  ws = new WebSocket(wsUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let nextId = 0;
  const pending = new Map();
  const waiters = [];
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      return;
    }
    for (const w of [...waiters]) {
      if (w.method === msg.method && w.sessionId === msg.sessionId) {
        waiters.splice(waiters.indexOf(w), 1);
        w.resolve(msg.params);
      }
    }
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
  const once = (method, sessionId) => new Promise((resolve) => waiters.push({ method, sessionId, resolve }));

  for (const job of jobs) {
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    const evaluate = async (expression) => {
      const res = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
      if (res.exceptionDetails) {
        throw new Error(`${job.out}: ${res.exceptionDetails.exception?.description || res.exceptionDetails.text}`);
      }
      return res.result.value;
    };
    await send("Page.enable", {}, sessionId);
    await send("Emulation.setDeviceMetricsOverride",
      { width: job.width, height: job.height, deviceScaleFactor: job.scale ?? 2, mobile: false }, sessionId);
    if (job.transparent) {
      await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } }, sessionId);
    }
    const loaded = once("Page.loadEventFired", sessionId);
    await send("Page.navigate", { url: job.url }, sessionId);
    await loaded;
    await evaluate("document.fonts.ready.then(() => true)");
    if (job.js) await evaluate(job.js);
    await sleep(job.wait ?? 500);
    await evaluate("document.fonts.ready.then(() => true)");

    let clip;
    if (job.selector) {
      const pad = job.pad ?? 0;
      const r = await evaluate(`(() => {
        const rects = ${JSON.stringify([].concat(job.selector))}.map((s) => {
          const el = document.querySelector(s);
          if (!el) throw new Error("no element for selector " + s);
          return el.getBoundingClientRect();
        });
        const x0 = Math.min(...rects.map((b) => b.left)), y0 = Math.min(...rects.map((b) => b.top));
        const x1 = Math.max(...rects.map((b) => b.right)), y1 = Math.max(...rects.map((b) => b.bottom));
        return { x: x0 + scrollX, y: y0 + scrollY, width: x1 - x0, height: y1 - y0 };
      })()`);
      clip = { x: Math.max(0, r.x - pad), y: Math.max(0, r.y - pad), width: r.width + 2 * pad, height: r.height + 2 * pad, scale: 1 };
    } else if (job.full) {
      clip = { x: 0, y: 0, width: job.width, height: await evaluate("document.documentElement.scrollHeight"), scale: 1 };
    }
    const { data } = await send("Page.captureScreenshot", { format: "png", clip, captureBeyondViewport: Boolean(clip) }, sessionId);
    mkdirSync(dirname(job.out), { recursive: true });
    writeFileSync(job.out, Buffer.from(data, "base64"));
    await send("Target.closeTarget", { targetId });
  }
} finally {
  ws?.close();
  // Wait for Chrome to exit before deleting its profile; the timeout covers a Chrome that never started.
  if (chrome.exitCode === null) await new Promise((r) => { chrome.once("exit", r); chrome.kill(); setTimeout(r, 5000); });
  rmSync(profile, { recursive: true, force: true, maxRetries: 3 });
}
