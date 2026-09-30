// Headless Chrome over the DevTools protocol, no npm packages: one launch and message
// handler, and a small browser + page API for frame-by-frame video capture.
import { spawn } from "node:child_process";
import { accessSync, constants, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url)); // scripts/video
export const REPO_ROOT = resolve(SCRIPT_DIR, "..", "..");
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const MAC_CHROME = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
];
const PATH_CHROME = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"];

const executable = (file) => {
  try {
    accessSync(file, constants.X_OK);
    return true;
  } catch {
    return false;
  }
};

// CHROME if set, else the standard macOS install, else google-chrome or chromium on PATH.
export function findChrome() {
  if (process.env.CHROME) {
    if (!executable(process.env.CHROME)) throw new Error(`CHROME is set but is not an executable file: ${process.env.CHROME}`);
    return process.env.CHROME;
  }
  const onPath = (name) => (process.env.PATH || "").split(delimiter).filter(Boolean).map((d) => join(d, name)).find(executable);
  const found = MAC_CHROME.find(executable) ?? PATH_CHROME.map(onPath).find(Boolean);
  if (!found) {
    throw new Error(`Chrome or Chromium not found. Install one, or set CHROME to its binary (looked for ${MAC_CHROME.join(", ")} and ${PATH_CHROME.join(", ")} on PATH).`);
  }
  return found;
}

// A signed-out, clean browser: a fresh throwaway profile in the system temp directory for every run,
// never the user's, deleted again on close.
export async function launchBrowser() {
  const binary = findChrome();
  const profile = mkdtempSync(join(tmpdir(), "attackgraph-video-chrome-"));
  const chrome = spawn(
    binary,
    [
      "--headless=new",
      "--remote-debugging-port=0",
      `--user-data-dir=${profile}`,
      "--hide-scrollbars",
      "--no-first-run",
      "--no-default-browser-check",
      "--font-render-hinting=none",
      "--disable-extensions",
      "--disable-sync",
      "--disable-background-networking",
      "--disable-component-update",
      "--mute-audio",
      "--lang=en-US",
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  let wsUrl;
  try {
    wsUrl = await new Promise((resolve, reject) => {
      let buf = "";
      chrome.on("error", (e) => reject(new Error(`Chrome did not start (${binary}): ${e.message}`)));
      chrome.stderr.on("data", (d) => {
        buf += d;
        const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
        if (m) resolve(m[1]);
      });
      setTimeout(() => reject(new Error(`Chrome did not start (${binary}):\n${buf}`)), 20000);
    });
  } catch (e) {
    chrome.kill();
    rmSync(profile, { recursive: true, force: true });
    throw e;
  }
  const ws = new WebSocket(wsUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let nextId = 0;
  const pending = new Map();
  const listeners = new Set();
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      return;
    }
    for (const l of [...listeners]) l(msg);
  });
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
  const once = (method, sessionId, timeout = 60000) =>
    new Promise((resolve, reject) => {
      const t = setTimeout(() => {
        listeners.delete(l);
        reject(new Error(`timeout waiting for ${method}`));
      }, timeout);
      const l = (msg) => {
        if (msg.method === method && msg.sessionId === sessionId) {
          clearTimeout(t);
          listeners.delete(l);
          resolve(msg.params);
        }
      };
      listeners.add(l);
    });

  async function newPage({ width = 1536, height = 864, scale = 1.25, transparent = false } = {}) {
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    const s = (method, params) => send(method, params, sessionId);
    await s("Page.enable");
    await s("Runtime.enable");
    await s("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: scale, mobile: false });
    if (transparent) await s("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
    const consoleErrors = [];
    listeners.add((msg) => {
      if (msg.sessionId === sessionId && msg.method === "Runtime.exceptionThrown") consoleErrors.push(msg.params.exceptionDetails?.text);
    });
    const page = {
      width,
      height,
      scale,
      sessionId,
      send: s,
      consoleErrors,
      async evaluate(expression) {
        const res = await s("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
        if (res.exceptionDetails) {
          throw new Error(`evaluate: ${res.exceptionDetails.exception?.description || res.exceptionDetails.text}\n--- in ---\n${expression.slice(0, 300)}`);
        }
        return res.result.value;
      },
      async goto(url, { timeout = 60000 } = {}) {
        const loaded = once("Page.loadEventFired", sessionId, timeout);
        await s("Page.navigate", { url });
        await loaded;
        await page.evaluate("document.fonts.ready.then(() => true)");
      },
      // Wait (in real time, nothing captured) until a JS expression is truthy.
      async waitFor(expression, { timeout = 30000, interval = 100, label = expression } = {}) {
        const t0 = Date.now();
        for (;;) {
          let v;
          try {
            v = await page.evaluate(expression);
          } catch (e) {
            v = false;
          }
          if (v) return v;
          if (Date.now() - t0 > timeout) throw new Error(`waitFor timed out after ${timeout} ms: ${String(label).slice(0, 200)}`);
          await sleep(interval);
        }
      },
      // Two animation frames, so a scroll or style change is painted before a capture.
      async settle() {
        await page.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))");
      },
      async screenshot({ format = "png", quality, clip, beyond = false } = {}) {
        const params = { format, captureBeyondViewport: beyond, optimizeForSpeed: format !== "png" };
        if (quality) params.quality = quality;
        if (clip) params.clip = clip;
        const { data } = await s("Page.captureScreenshot", params);
        return Buffer.from(data, "base64");
      },
      async close() {
        await send("Target.closeTarget", { targetId });
      },
    };
    return page;
  }

  return {
    send,
    newPage,
    async close() {
      try {
        ws.close();
      } catch {}
      chrome.kill();
      await new Promise((r) => (chrome.exitCode !== null || chrome.signalCode !== null ? r() : chrome.once("exit", r)));
      await sleep(300);
      rmSync(profile, { recursive: true, force: true });
    },
  };
}
