// The shot list. Each shot loads its page in a fresh signed-out browser, then drives the
// recorder: camera moves, clicks, and caption cues (text lives in captions.json).
// Positions are measured from the live DOM, so a reworded or redeployed page still frames.
// Shot 7's press log and replies go to the output's logs/ folder, which make.mjs passes in as ctx.logs.
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { sleep } from "./cdp.mjs";
import { VW, VH, findByText } from "./recorder.mjs";

export const HOSTED = "https://attackgraph-ai.vercel.app";
export const LOCAL = (process.env.APP_URL || "http://127.0.0.1:8599").replace(/\/+$/, ""); // the local Streamlit app
export const GITHUB = "https://github.com/Ducksss/attackgraph-ai";
const ST_MAIN = "[data-testid=stMain]";
const PRESS_LOG = "bedrock-presses.jsonl";
export const PRESS_BUDGET = 3;

// Streamlit is idle when no run is in progress and nothing is marked stale.
const ST_IDLE = `(() => !document.querySelector('[data-testid=stStatusWidget]') && !document.querySelector('[data-stale=true]'))()`;
// Streamlit buttons carry a Material icon ligature in their text ("healing..."), so match on the label.
const stButton = (label) => `[...document.querySelectorAll('button')].find((b) => b.textContent.includes(${JSON.stringify(label)}))`;

async function stReady(page, readyExpr) {
  await page.waitFor(readyExpr, { timeout: 60000, label: "streamlit content" });
  await page.waitFor(ST_IDLE, { timeout: 60000, label: "streamlit idle" });
  // Hover tooltips (the Explain button's "One Converse call to ..." help) pop up while the drawn cursor
  // dwells on a button, because every frame takes real time to capture; keep them out of the frame.
  await page.evaluate(`(() => { const s = document.createElement('style'); s.textContent = 'div[role="tooltip"], [data-testid="stTooltipContent"] { display: none !important; }'; document.head.append(s); return true; })()`);
  await page.evaluate("document.fonts.ready.then(() => true)");
  await sleep(1500);
}

// Signed-out GitHub: nothing personal on screen. Avatars are hidden (their space is kept).
async function githubPrep(page, readyText) {
  await page.waitFor(`document.body.innerText.includes(${JSON.stringify(readyText)})`, { timeout: 60000, label: readyText });
  await page.evaluate(`(() => { const s = document.createElement('style'); s.textContent = 'img.avatar, img.avatar-user, .avatar img { visibility: hidden !important; }'; document.head.append(s); return true; })()`);
  await page.evaluate("document.fonts.ready.then(() => true)");
  await sleep(1500);
}

// Bottom (content coordinates) of what is inside a Streamlit column: columns stretch to the
// height of their row, so the column's own box is no guide.
async function contentBottom(rec, columnSelector) {
  const col = await rec.box(columnSelector);
  const vb = await rec.page.evaluate(`(() => { const c = document.querySelector(${JSON.stringify(columnSelector)});
    const items = [...c.querySelectorAll('[data-testid=stElementContainer]')];
    return Math.max(...items.map((e) => e.getBoundingClientRect().bottom), c.getBoundingClientRect().top) - c.getBoundingClientRect().top; })()`);
  return col.y + vb;
}

export function pressCount(logs) {
  const file = join(logs, PRESS_LOG);
  if (!existsSync(file)) return 0;
  // One "pressed" line per click of Explain with Amazon Bedrock; outcome lines are not counted.
  return readFileSync(file, "utf8").split("\n").filter(Boolean).filter((l) => JSON.parse(l).outcome === "pressed").length;
}

function logPress(logs, entry) {
  mkdirSync(logs, { recursive: true });
  appendFileSync(join(logs, PRESS_LOG), JSON.stringify(entry) + "\n");
}

export const SHOTS = {
  1: {
    slug: "github-files",
    source: "GitHub (signed out)",
    url: `${GITHUB}/pull/3/files`,
    what: "PR #3, Files changed: line 27 of snapshots/app-prod.json, false to true, with the check's annotation",
    async prepare(page) {
      await githubPrep(page, "New path to a protected role");
    },
    async run(rec) {
      const title = await rec.box("h1");
      const table = await rec.box("table");
      rec.cam = { x: 0, y: title.y - 22, w: VW }; // GitHub's header scrolled away: title, tabs, diff, notes
      await rec.say("s1a");
      await rec.hold(4.2);
      await rec.say("s1b");
      // Push in on the diff: line numbers through the "false" / "true" values, and the note under line 27.
      await rec.move({ x: table.x - 14, y: table.y - 64, w: 1240 }, 1.6);
      await rec.hold(3.0);
      await rec.say("s1c"); // lines 28-30 below: the older grants the change completes
      await rec.hold(4.6);
    },
  },

  2: {
    slug: "github-check",
    source: "GitHub (signed out)",
    url: `${GITHUB}/actions/runs/36677079723`,
    what: "The PR's latest Permission check run: AttackGraph AI failed, annotation 'New path to a protected role'",
    async prepare(page) {
      await githubPrep(page, "New path to a protected role");
    },
    async run(rec) {
      const header = await rec.box("page-header");
      const notes = await rec.box({ text: "Annotations", tag: "h2" });
      rec.cam = { x: 0, y: header.y - 14, w: VW }; // just below GitHub's header and repository tabs
      await rec.say("s2a");
      await rec.hold(4.1);
      await rec.say("s2b");
      await rec.move({ x: notes.x - 30, y: notes.y - 200, w: 1060 }, 1.6);
      await rec.hold(3.8);
      await rec.say("s2c");
      await rec.hold(4.1);
    },
  },

  3: {
    slug: "hosted-hero",
    source: "Hosted site, overview (hero)",
    url: `${HOSTED}/`,
    hostedOverview: true,
    what: "Overview hero: headline, 'then tests the fix', and the diagram: 7 conditions, engine, new path found, verified fix",
    async prepare(page) {
      await page.waitFor("!!document.querySelector('.ag-hero .ag-flow')", { timeout: 30000 });
      await sleep(1200);
    },
    async run(rec) {
      const pill = await rec.box(".ag-hero .ag-pill");
      const quote = await rec.box(".ag-proof-quote");
      const stats = await rec.box(".ag-proof-stats");
      // Headline, lead ("... then tests the fix."), buttons and the diagram; the strip's text starts below the frame,
      // so nothing dark sits under the caption box.
      const flow = await rec.box(".ag-hero .ag-flow");
      rec.cam = { x: 0, y: Math.min(pill.y - 16, quote.y - VH - 6), w: VW };
      await rec.say("s3a");
      await rec.hold(1.8);
      // Down to the diagram with the strip under it (0 -> 1 high-risk paths, baseline to proposed; 7 of 7),
      // so the caption sits over the strip's small print rather than the diagram.
      await rec.move({ y: Math.min(flow.y - 14, stats.y + stats.h - VH * 0.83 + 10) }, 2.6);
      await rec.hold(0.8);
      await rec.say("s3b");
      await rec.hold(5.2);
    },
  },

  4: {
    slug: "local-pull-request",
    source: "Local app (Streamlit, /demo)",
    url: `${LOCAL}/demo`,
    scroller: ST_MAIN,
    what: "The pull request card: diff, note on line 27, failing check; Apply the suggested fix; check passes",
    async prepare(page) {
      await stReady(page, `!!${stButton("Apply the suggested fix")}`);
    },
    async run(rec) {
      const card = await rec.box(".st-key-agcard-pr");
      const note = await rec.box(".st-key-agcard-pr .ag-annot");
      const check = await rec.box(".st-key-agcard-pr .ag-pr-check");
      rec.cam = { x: 0, y: 0, w: VW };
      await rec.say("s4a");
      await rec.hold(1.2);
      await rec.move(rec.fit(card, { margin: 14 }), 2.4); // the whole card: diff, note, failing check, button
      await rec.hold(0.8);
      await rec.move(rec.fit([note, check], { margin: 20, maxZoom: 1.45, align: "center" }), 1.4); // the note on line 27 and exit status 1
      await rec.hold(2.2);
      await rec.move(rec.fit(card, { margin: 14 }), 1.2);
      await rec.hold(0.3);
      await rec.say("s4b");
      await rec.click({ text: "Apply the suggested fix", tag: "p", within: ".st-key-pr-apply" }, {
        wait: `(() => { const c = document.querySelector('.st-key-agcard-pr'); return !!c && /Check passed/.test(c.textContent) && ${ST_IDLE}; })()`,
      });
      const fixed = await rec.box(".st-key-agcard-pr");
      await rec.move(rec.fit(fixed, { margin: 18 }), 1.1); // the fix commit and the passing check, closer
      await rec.hold(1.0);
      await rec.say("s4c");
      const passed = await rec.box(".st-key-agcard-pr .ag-pr-check");
      const diff = await rec.box(".st-key-agcard-pr .ag-diff-file");
      await rec.move(rec.fit([diff, passed], { margin: 20, maxZoom: 1.45, align: "center" }), 1.3); // true -> false, exit status 0
      await rec.hold(2.9);
    },
  },

  5: {
    slug: "local-path",
    source: "Local app (Streamlit, /demo)",
    url: `${LOCAL}/demo`,
    scroller: ST_MAIN,
    what: "Verdict '1 new path to a protected role', stats, The path it opens (amber arrow), The change",
    async prepare(page) {
      await stReady(page, "!!document.querySelector('.st-key-agcard-change')");
    },
    async run(rec) {
      const inside = await rec.box(".ag-inside");
      const stats = await rec.box(".ag-stats");
      const path = await rec.box(".st-key-agcard-path");
      const change = await rec.box(".st-key-agcard-change");
      rec.cam = rec.fit([inside, stats, path], { align: "bottom", margin: 16 }); // verdict, the four numbers, the route
      await rec.say("s5a");
      await rec.hold(5.3);
      await rec.say("s5b");
      await rec.move(rec.fit([path, change], { align: "bottom", margin: 16 }), 1.8); // the route and the fact behind it
      await rec.hold(3.6);
      await rec.say("s5c"); // the amber arrow; false -> true in The change
      await rec.hold(4.0);
    },
  },

  6: {
    slug: "local-conditions",
    source: "Local app (Streamlit, /demo)",
    url: `${LOCAL}/demo`,
    scroller: ST_MAIN,
    what: "Why the route works: 7 of 7 hold, the changed condition, the scenario assumption",
    async prepare(page) {
      await stReady(page, "!!document.querySelector('.st-key-agcard-conds')");
    },
    async run(rec) {
      const path = await rec.box(".st-key-agcard-path");
      const change = await rec.box(".st-key-agcard-change");
      const conds = await rec.box(".st-key-agcard-conds");
      rec.cam = rec.fit([path, change], { align: "bottom", margin: 16 }); // where shot 5 ended
      await rec.say("s6a");
      await rec.hold(0.5);
      await rec.move(rec.fit(conds), 1.8); // the same framing shot 7 (the live take) opens on, so the cut does not jump
      await rec.hold(2.5);
      await rec.say("s6b");
      await rec.hold(4.0);
      await rec.say("s6c");
      await rec.hold(3.3);
    },
  },

  7: {
    slug: "local-bedrock",
    source: "Local app (Streamlit, /demo), live Amazon Bedrock call",
    url: `${LOCAL}/demo`,
    scroller: ST_MAIN,
    what: "What this means: Explain with Amazon Bedrock, the live reply with names as tags, Model/Region/Request, What the model sees",
    live: true,
    async prepare(page) {
      await stReady(page, `!!${stButton("Explain with Amazon Bedrock")}`);
    },
    async run(rec, ctx) {
      const conds = await rec.box(".st-key-agcard-conds");
      const ai = await rec.box(".st-key-agcard-ai");
      rec.cam = rec.fit(conds); // where shot 6 ended
      await rec.say("s7a");
      await rec.hold(0.3);
      await rec.move(rec.fit(ai), 1.5);
      await rec.hold(0.9);
      const replied = `(() => { const c = document.querySelector('.st-key-agcard-ai'); if (!c) return false;
        const t = c.textContent; return (/AI explanation unavailable/.test(t) || /Request/.test(t)) && ${ST_IDLE}; })()`;
      await rec.click({ text: "Explain with Amazon Bedrock", tag: "p", within: ".st-key-agcard-ai" }, {
        press: !ctx.dry, // a rehearsal never presses the chargeable button
        wait: ctx.dry ? null : replied,
        waitTimeout: 60000,
        during: ctx.dry ? 0 : 0.5,
        onClicked: async () => {
          if (!ctx.dry) logPress(ctx.logs, { at: new Date().toISOString(), shot: 7, outcome: "pressed" });
        },
      });
      // What came back, kept for review (no credentials are on the page; the request ID is fine to show).
      const reply = await rec.page.evaluate(`(() => { const c = document.querySelector('.st-key-agcard-ai');
        return { text: c.innerText, unavailable: /AI explanation unavailable/.test(c.textContent) }; })()`);
      if (!ctx.dry) {
        mkdirSync(ctx.logs, { recursive: true });
        writeFileSync(join(ctx.logs, `bedrock-reply-${Date.now()}.json`), JSON.stringify(reply, null, 1));
        logPress(ctx.logs, { at: new Date().toISOString(), shot: 7, outcome: reply.unavailable ? "unavailable" : "reply" });
        if (reply.unavailable) throw new Error("AI explanation unavailable: use the recorded fallback (node scripts/video/make.mjs 7 --recorded)");
      }
      const card = await rec.box(".st-key-agcard-ai");
      await rec.move(rec.fit(card, { maxZoom: 1.3 }), 1.0); // the reply and the Model / Region / Request rows
      await rec.say("s7b");
      await rec.hold(4.2);
      await rec.click({ text: "What the model sees", tag: "p", within: ".st-key-agcard-ai" }, {
        wait: `(() => { const c = document.querySelector('.st-key-agcard-ai'); return !!c && !!c.querySelector('[data-testid=stCode]') && ${ST_IDLE}; })()`,
      });
      await rec.say("s7c");
      // Close on the evidence packet: aliases such as P1, R1 and F1 are all the model gets. The close-up
      // starts below the reply in the left column, so no cut-off text from it shares the frame.
      const code = await rec.box(".st-key-agcard-ai [data-testid=stCode]");
      const leftBottom = await contentBottom(rec, ".st-key-agcard-ai [data-testid=stColumn]");
      const w = 800;
      const top = Math.max(code.y - 64, leftBottom + 12);
      await rec.move({ x: code.x + code.w / 2 - w / 2, y: top, w }, 1.4);
      await rec.hold(2.6);
      await rec.say("s7d");
      await rec.hold(2.2);
      await rec.say("s7e");
      await rec.move(rec.fit(card, { maxZoom: 1.3 }), 1.4);
      await rec.hold(2.8);
      const field = (k) => (reply.text.match(new RegExp(`${k}\\n([^\\n]+)`)) || [])[1] || null;
      return { variant: ctx.dry ? "dry" : "live", reply: { unavailable: reply.unavailable, request: field("Request"), tokens: field("Tokens"),
        latency: field("Latency"), model: field("Model"), region: field("Region"), prompt: field("Prompt"), press: pressCount(ctx.logs) } };
    },
  },

  "7r": {
    slot: 7,
    slug: "hosted-recorded-reply",
    source: "Hosted site, demo (recorded AI reply)",
    url: `${HOSTED}/demo`,
    what: "Fallback: What this means with the recorded Nova Pro reply and its date",
    async prepare(page) {
      await page.waitFor("document.body.innerText.includes('Recorded AI explanation')", { timeout: 30000 });
      await sleep(1200);
    },
    async run(rec) {
      const heading = await rec.box({ text: "What this means", tag: "h3" });
      rec.cam = { x: 0, y: heading.y - 60, w: VW };
      await rec.say("s7r_a");
      await rec.hold(5.0);
      await rec.say("s7r_b");
      await rec.hold(4.5);
      await rec.say("s7c");
      await rec.hold(3.0);
      await rec.say("s7d");
      await rec.hold(3.8);
      await rec.say("s7e");
      await rec.hold(4.0);
      return { variant: "recorded" };
    },
  },

  8: {
    slug: "local-fix",
    source: "Local app (Streamlit, /demo)",
    url: `${LOCAL}/demo`,
    scroller: ST_MAIN,
    what: "The fix: Simulate the fix; the cut route, 1 -> 0, 2 of 2, Verified in this model",
    async prepare(page) {
      await stReady(page, `!!${stButton("Simulate the fix")}`);
    },
    async run(rec) {
      const fix = await rec.box(".st-key-agcard-fix");
      rec.cam = rec.fit(fix);
      // No caption until the click: before it, the page footer sits where the caption goes.
      await rec.hold(0.8);
      await rec.click({ text: "Simulate the fix", tag: "p", within: ".st-key-agcard-fix" }, {
        anchor: ".st-key-agcard-fix",
        wait: `(() => !!document.querySelector('.st-key-agcard-fix .ag-fix-result') && ${ST_IDLE})()`,
      });
      await rec.say("s8a");
      const after = await rec.box(".st-key-agcard-fix");
      await rec.move(rec.fit(after, { margin: 18 }), 1.2); // the cut route, 1 -> 0, 2 of 2 and the badge in one view
      await rec.hold(3.4);
      await rec.say("s8b");
      const result = await rec.box(".st-key-agcard-fix .ag-fix-result");
      await rec.move(rec.fit(result, { margin: 20, maxZoom: 1.45 }), 1.3); // the cut route and the two numbers, closer
      await rec.hold(3.8);
      await rec.say("s8c");
      await rec.move(rec.fit(after, { margin: 18 }), 1.3);
      await rec.hold(3.2);
    },
  },

  9: {
    slug: "hosted-trust",
    source: "Hosted site, overview (Trust and limits)",
    url: `${HOSTED}/`,
    hostedOverview: true,
    what: "Trust and limits: the six chips; FAQ 'Can it block a pull request?' and 'What is out of scope?' opened",
    async prepare(page) {
      await page.waitFor("!!document.querySelector('#trust')", { timeout: 30000 });
      await sleep(1200);
    },
    async run(rec) {
      const trust = await rec.box("#trust");
      // Open a little closer, so the next section's large heading stays below the frame instead of under
      // the caption; widen out as the answers open (they push that section down).
      const w0 = 1220;
      rec.cam = { x: (VW - w0) / 2, y: trust.y - 62, w: w0 };
      await rec.say("s9a");
      await rec.hold(1.9);
      await rec.click({ text: "Can it block a pull request?", tag: "summary" }, { approach: 0.7 });
      await rec.hold(2.1);
      await rec.say("s9b");
      await rec.click({ text: "What is out of scope?", tag: "summary" }, { approach: 0.6 });
      await rec.hold(0.4);
      await rec.move({ x: 0, w: VW, y: trust.y - 30 }, 1.3); // the whole section, both answers above the caption
      await rec.hold(1.0);
      await rec.say("s9c");
      await rec.hold(3.4);
    },
  },
};

export { findByText };
