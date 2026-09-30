// Render pages to PNG with headless Chrome over the DevTools protocol, using no npm packages.
// scripts/build_assets.py drives it. It needs Node 22 or newer, for the built-in WebSocket, and
// Chrome at $CHROME (default: the macOS install path).
//
// usage: node scripts/assets/shoot.mjs jobs.json
// job: {url, out, width, height, scale = 2, transparent = false, js?, selector?, pad = 0, full = false, wait = 500,
//       fonts = [], timeout = 60000}
// selector may be a list, which crops to the union of the elements' boxes. fonts lists the font faces the page
// must have, as [family, weight] pairs. timeout is the job's deadline in milliseconds, from opening its tab to
// writing its file; when it passes, every wait of the job rejects.
//
// A job fails when it overruns its deadline, when a stylesheet, font or image fails to load, or when a face in
// fonts is not registered or did not load. document.fonts.ready resolves in all of these cases, and the capture
// would show fallback text or icon names. The run then stops with exit status 1 and writes no file for that job.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const JOB_TIMEOUT = 60000;
const WATCHED = new Set(["Stylesheet", "Font", "Image"]); // resource types whose failure spoils a render
const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const profile = mkdtempSync(join(tmpdir(), "attackgraph-chrome-"));
const chrome = spawn(
  CHROME,
  ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--hide-scrollbars",
   "--no-first-run", "--no-default-browser-check", "--font-render-hinting=none", "about:blank"],
  { stdio: ["ignore", "ignore", "pipe"] },
);

// Runs in the page before capture and lists what is wrong with its fonts. document.fonts.check() is no help:
// it returns true for a family that no stylesheet registered, because nothing is left to load.
async function fontProblems(fonts) {
  await document.fonts.ready;
  const problems = [];
  const family = (face) => face.family.replace(/^["']|["']$/g, "");
  const weights = (face) => face.weight.split(" ").map((w) => ({ normal: 400, bold: 700 })[w] ?? Number(w));
  for (const [name, weight] of fonts) {
    let faces;
    try {
      faces = await document.fonts.load(`${weight} 16px "${name}"`);
    } catch {
      problems.push(`font ${name} ${weight} did not load`);
      continue;
    }
    // No faces means no stylesheet registered the family; a missing weight comes back as the nearest one.
    const face = faces.find((f) => family(f) === name && weights(f)[0] <= weight && weight <= weights(f).at(-1));
    if (!face) problems.push(`font ${name} ${weight} is not registered`);
    else if (face.status !== "loaded") problems.push(`font ${name} ${weight} did not load`);
  }
  for (const face of document.fonts) if (face.status === "error") problems.push(`font ${family(face)} ${face.weight} did not load`);
  return [...new Set(problems)];
}

let ws;
let lost = null; // why the DevTools connection is gone
let halted = null; // why the current job must stop; every wait rejects with it
let watched = null; // the current job's session, whose failed requests are collected
let failed = []; // the current job's failed stylesheet, font and image requests
const urls = new Map(); // request id -> URL, for the current job's session
const pending = new Map(); // command id -> {resolve, reject}
const waiters = new Set(); // events and pauses the current job waits for

// Reject every outstanding command and wait with the first reason given.
function halt(error) {
  halted ??= error;
  for (const p of pending.values()) p.reject(halted);
  pending.clear();
  for (const w of waiters) w.reject(halted);
  waiters.clear();
}

let nextId = 0;
function send(method, params = {}, sessionId) {
  if (halted) return Promise.reject(halted);
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}

// The next `method` event in the session; with ms, a pause of ms instead.
function wait(method, sessionId, ms) {
  if (halted) return Promise.reject(halted);
  const promise = new Promise((resolve, reject) => {
    const w = { method, sessionId, resolve, reject };
    if (ms !== undefined) {
      const timer = setTimeout(() => {
        waiters.delete(w);
        resolve();
      }, ms);
      w.reject = (error) => {
        clearTimeout(timer);
        reject(error);
      };
    }
    waiters.add(w);
  });
  promise.catch(() => {}); // it can be rejected before the job gets round to awaiting it
  return promise;
}
const once = (method, sessionId) => wait(method, sessionId);
const pause = (ms) => wait(null, null, ms);

function network(msg) {
  const p = msg.params;
  const short = (url) => (url.length > 120 ? `${url.slice(0, 50)}...${url.slice(-67)}` : url); // keeps host and file
  if (msg.method === "Network.requestWillBeSent") urls.set(p.requestId, p.request.url);
  else if (msg.method === "Network.responseReceived" && WATCHED.has(p.type) && p.response.status >= 400) {
    failed.push(`${p.type.toLowerCase()} ${short(p.response.url)} returned HTTP ${p.response.status}`);
  } else if (msg.method === "Network.loadingFailed" && WATCHED.has(p.type) && !p.canceled) {
    failed.push(`${p.type.toLowerCase()} ${short(urls.get(p.requestId) ?? p.requestId)} did not load (${p.errorText})`);
  }
}

async function shoot(job) {
  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  watched = sessionId;
  const evaluate = async (expression) => {
    const res = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
    if (res.exceptionDetails) throw new Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text);
    return res.result.value;
  };
  await send("Page.enable", {}, sessionId);
  await send("Network.enable", {}, sessionId);
  await send("Emulation.setDeviceMetricsOverride",
    { width: job.width, height: job.height, deviceScaleFactor: job.scale ?? 2, mobile: false }, sessionId);
  if (job.transparent) {
    await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } }, sessionId);
  }
  const loaded = once("Page.loadEventFired", sessionId);
  const { errorText } = await send("Page.navigate", { url: job.url }, sessionId);
  if (errorText) throw new Error(`could not open ${job.url} (${errorText})`);
  await loaded;
  await evaluate("document.fonts.ready.then(() => true)");
  if (job.js) await evaluate(job.js);
  await pause(job.wait ?? 500);
  const fontIssues = await evaluate(`(${fontProblems})(${JSON.stringify(job.fonts ?? [])})`);
  const problems = [...new Set([...failed, ...fontIssues])];
  if (problems.length) throw new Error(problems.join("; "));

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

// Wait for Chrome to exit before its profile is deleted: SIGTERM, then SIGKILL if it lingers.
async function stopChrome() {
  for (const [signal, ms] of [["SIGTERM", 5000], ["SIGKILL", 2000]]) {
    if (!chrome.pid || chrome.exitCode !== null || chrome.signalCode !== null) return;
    let timer;
    await new Promise((resolve) => {
      timer = setTimeout(resolve, ms);
      chrome.once("exit", resolve);
      chrome.kill(signal);
    });
    clearTimeout(timer);
  }
}

try {
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = "";
    const timer = setTimeout(() => reject(new Error("Chrome did not start:\n" + buf)), 20000);
    const onData = (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) settle(resolve, m[1]);
    };
    const settle = (fn, value) => {
      clearTimeout(timer);
      chrome.stderr.off("data", onData); // the stream keeps flowing, so later output is dropped, not buffered
      fn(value);
    };
    chrome.on("error", (e) => settle(reject, e));
    chrome.on("exit", (code) => settle(reject, new Error(`Chrome exited (${code}) before it started:\n${buf}`)));
    chrome.stderr.on("data", onData);
  });

  ws = new WebSocket(wsUrl);
  const gone = (why) => () => {
    lost ??= new Error(`the DevTools connection ${why}`);
    halt(lost);
  };
  ws.addEventListener("error", gone("failed"));
  ws.addEventListener("close", gone("closed"));
  ws.addEventListener("message", (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id !== undefined) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? p?.reject(new Error(JSON.stringify(msg.error))) : p?.resolve(msg.result);
      return;
    }
    if (msg.sessionId === watched) network(msg);
    for (const w of waiters) {
      if (w.method === msg.method && w.sessionId === msg.sessionId) {
        waiters.delete(w);
        w.resolve(msg.params);
      }
    }
  });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("the DevTools connection did not open")), 10000);
    ws.addEventListener("open", () => {
      clearTimeout(timer);
      resolve();
    });
    ws.addEventListener("close", () => {
      clearTimeout(timer);
      reject(lost);
    });
  });

  for (const job of jobs) {
    halted = lost;
    failed = [];
    urls.clear();
    const ms = job.timeout ?? JOB_TIMEOUT;
    const deadline = setTimeout(() => halt(new Error(`timed out after ${ms / 1000} s`)), ms);
    try {
      await shoot(job);
    } catch (e) {
      throw new Error(`${job.out}: ${e.message}`);
    } finally {
      clearTimeout(deadline);
      halt(new Error("the job is over")); // drop any wait it left behind, such as a load event that never came
      watched = null;
    }
  }
} catch (e) {
  console.error(`shoot.mjs: ${e.message}`);
  process.exitCode = 1;
} finally {
  ws?.close();
  await stopChrome();
  try {
    // Chrome's helper processes can still write to the profile for a moment after Chrome exits.
    rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
  } catch (e) {
    console.error(`shoot.mjs: could not delete the Chrome profile ${profile} (${e.code})`);
  }
}
