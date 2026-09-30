// The optional voice-over: the captions read aloud by an ElevenLabs voice and mixed into one narration track.
// make.mjs --voice calls narrate() after assembling the silent cut; --voice-dry passes dry, which puts a tone
// in place of each request and never reads the key.
//
// Each line is trimmed of silence at both ends and starts with its caption. It is sped up only to fit its slot,
// the gap to the next line less GAP, and never beyond MAX_TEMPO; a line that still runs long pushes the next
// one later, PUSH after it ends. The lines are mixed, normalised to -16 LUFS and encoded as AAC.
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SCRIPT_DIR, sleep } from "./cdp.mjs";
import { FFMPEG, FFPROBE, FPS } from "./recorder.mjs";

export const VOICE = JSON.parse(readFileSync(join(SCRIPT_DIR, "voice.json"), "utf8"));
export const DEFAULT_VOICE_ID = "iP95p4xoKVk53GoZ742B"; // Chris: a premade voice, which the free plan can use over the API
export const MODEL = "eleven_multilingual_v2";
const API = "https://api.elevenlabs.io/v1/text-to-speech";
const FORMAT = "mp3_44100_128";
const SETTINGS = { stability: 0.5, similarity_boost: 0.75, style: 0, use_speaker_boost: true };
export const GAP = 0.15; // silence kept before the next line's slot starts
export const PUSH = 0.12; // the gap after a line that ran long, before the line it pushed
export const MAX_TEMPO = 1.12;
const TAIL = 0.25; // the last line ends this long before the cut does
const RATE = 48000;
const TRIM = "silenceremove=start_periods=1:start_threshold=-45dB"; // at both ends, via areverse
const DRY_RATE = 15; // characters per second of a rehearsal tone, a little slower than the voice
const pad2 = (n) => String(n).padStart(2, "0");

function run(cmd, argv) {
  const r = spawnSync(cmd, argv, { stdio: ["ignore", "inherit", "inherit"] });
  if (r.status !== 0) throw new Error(`${cmd} failed (${r.status ?? r.error?.message})`);
}

function seconds(file) {
  const r = spawnSync(FFPROBE, ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", file], { encoding: "utf8" });
  return Number(r.stdout.trim());
}

// A caption as it is spoken: voice.json's substitutions, in order.
export function spoken(text) {
  return VOICE.say.reduce((s, [from, to]) => s.split(from).join(to), text);
}

// The lines to speak, from make.mjs's timeline: the title line, every caption, and the end line.
export function voiceLines(items) {
  const lines = [];
  for (const it of items) {
    if (it.key === "title" || it.key === "end") lines.push({ id: it.key, at: it.start + VOICE[it.key].at, text: VOICE[it.key].text });
    else for (const c of it.cues) lines.push({ id: c.id, at: it.start + c.start / FPS, caption: c.text, text: spoken(c.text) });
  }
  return lines;
}

// When each line starts and how much it is sped up, given its trimmed length in `seconds`.
export function schedule(lines, total) {
  let end = -Infinity;
  return lines.map((line, i) => {
    const next = i + 1 < lines.length ? lines[i + 1].at : total - TAIL;
    const slot = next - line.at - GAP;
    const tempo = slot > 0 ? Math.min(MAX_TEMPO, Math.max(1, line.seconds / slot)) : MAX_TEMPO;
    const start = Math.max(line.at, end + PUSH);
    end = start + line.seconds / tempo;
    return { ...line, slot, tempo, start, end };
  });
}

// The request body for line i, and the cache file its audio is kept in, named by everything that shapes the
// audio: the voice, the format and the body. Never by the key.
export function request(lines, i, voiceId) {
  const body = { text: lines[i].text, model_id: MODEL, voice_settings: SETTINGS };
  if (i > 0) body.previous_text = lines[i - 1].text; // for continuity of tone between separate requests
  if (i + 1 < lines.length) body.next_text = lines[i + 1].text;
  const hash = createHash("sha256").update(JSON.stringify({ voiceId, FORMAT, body })).digest("hex").slice(0, 20);
  return { body, name: `${hash}.mp3` };
}

// One text-to-speech request, or its cached audio.
async function speak(lines, i, { key, voiceId, cache, log }) {
  const line = lines[i];
  const { body, name } = request(lines, i, voiceId);
  const file = join(cache, name);
  if (existsSync(file)) return { file, source: "cache" };
  // The key goes in the request header only; scrub it from anything that could reach a message.
  const scrub = (s) => String(s).split(key).join("[ELEVENLABS_API_KEY]");
  const url = `${API}/${encodeURIComponent(voiceId)}?output_format=${FORMAT}`;
  log(`voice: line ${i + 1}/${lines.length} ${line.id}, ${line.text.length} characters, from ElevenLabs`);
  for (let attempt = 1; ; attempt++) {
    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "xi-api-key": key, "content-type": "application/json", accept: "audio/mpeg" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(60000),
      });
    } catch (e) {
      if (attempt < 3) {
        await sleep(2000 * attempt);
        continue;
      }
      throw new Error(`ElevenLabs request for ${line.id} failed: ${scrub(e.message)}`);
    }
    if (res.ok && /^audio\//.test(res.headers.get("content-type") || "")) {
      const audio = Buffer.from(await res.arrayBuffer());
      writeFileSync(`${file}.part`, audio);
      renameSync(`${file}.part`, file);
      return { file, source: "ElevenLabs" };
    }
    const text = await res.text().catch(() => "");
    if ((res.status === 429 || res.status >= 500) && attempt < 3) {
      await sleep(2000 * attempt);
      continue;
    }
    let detail = text;
    try {
      const d = JSON.parse(text).detail;
      detail = typeof d === "string" ? d : d?.message || d?.status || JSON.stringify(d);
    } catch {}
    throw new Error(`ElevenLabs refused ${line.id}: HTTP ${res.status} ${scrub(detail).slice(0, 300)}`);
  }
}

// A rehearsal tone in place of a request: about as long as the line, with silence at both ends to trim.
function tone(lines, i, dir) {
  const file = join(dir, `tone-${pad2(i)}.wav`);
  const d = Math.max(1, lines[i].text.length / DRY_RATE);
  run(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", `sine=frequency=${i % 2 ? 660 : 440}:sample_rate=44100:duration=${d.toFixed(2)}`,
    "-af", "adelay=300,apad=pad_dur=0.6", "-ac", "1", file]);
  return { file, source: "tone" };
}

function mix(lines, total, out, script) {
  const filters = lines.map((l, i) => `[${i}:a]${l.tempo > 1 ? `atempo=${l.tempo.toFixed(3)},` : ""}adelay=${Math.round(l.start * RATE)}S:all=1[a${i}]`);
  filters.push(`${lines.map((_, i) => `[a${i}]`).join("")}amix=inputs=${lines.length}:duration=longest:normalize=0,` +
    `apad=whole_dur=${total.toFixed(3)},atrim=end=${total.toFixed(3)},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=${RATE}[out]`);
  writeFileSync(script, filters.join(";\n"));
  run(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", ...lines.flatMap((l) => ["-i", l.wav]), "-filter_complex_script", script,
    "-map", "[out]", "-c:a", "aac", "-b:a", "128k", "-ar", String(RATE), "-ac", "2", out]);
}

// Voice the lines into dir/narration.m4a, total seconds long; dir/plan.json records what was said and when.
export async function narrate(lines, total, { dir, dry = false, log = console.log }) {
  const cache = join(dir, "cache");
  mkdirSync(dry ? dir : cache, { recursive: true });
  const key = dry ? null : process.env.ELEVENLABS_API_KEY;
  if (!dry && !key) throw new Error("the voice-over needs ELEVENLABS_API_KEY; --voice-dry rehearses it with tones and no API calls");
  const voiceId = dry ? "tone" : process.env.ELEVENLABS_VOICE_ID || DEFAULT_VOICE_ID;
  const warnings = [];
  const warn = (w) => {
    warnings.push(w);
    log(`voice warning: ${w}`);
  };
  // Reported before any request, so a line that would be read badly can be fixed before it costs characters.
  for (const l of lines) if (/\d/.test(l.text)) warn(`${l.id} is read with digits: "${l.text}" (add a substitution to voice.json)`);
  const chars = lines.reduce((a, l) => a + l.text.length, 0);
  log(`voice: ${lines.length} lines, ${chars.toLocaleString("en-US")} characters, ${dry ? "rehearsed with tones" : `voice ${voiceId}, ${MODEL}`}`);
  const voiced = [];
  for (let i = 0; i < lines.length; i++) {
    const { file, source } = dry ? tone(lines, i, dir) : await speak(lines, i, { key, voiceId, cache, log });
    const wav = join(dir, `${pad2(i)}.wav`);
    run(FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", "-i", file, "-af", `${TRIM},areverse,${TRIM},areverse,aresample=${RATE}`,
      "-ac", "2", "-c:a", "pcm_s16le", wav]);
    const length = seconds(wav);
    if (!(length > 0.1)) throw new Error(`voice line ${lines[i].id} is silent after trimming (${file})`);
    voiced.push({ ...lines[i], seconds: length, wav, source });
  }
  const planned = schedule(voiced, total);
  for (const l of planned) if (l.end > total - 0.05) warn(`${l.id} ends at ${l.end.toFixed(2)} s, past the end of the cut (${total.toFixed(2)} s)`);
  const file = join(dir, "narration.m4a");
  mix(planned, total, file, join(dir, "narration-filter.txt"));
  const round = (x, places = 3) => Number(x.toFixed(places));
  const record = planned.map(({ wav, ...l }) => ({ ...l, at: round(l.at), seconds: round(l.seconds), slot: round(l.slot), tempo: round(l.tempo),
    start: round(l.start), end: round(l.end), drift: round(l.start - l.at), chars: l.text.length }));
  writeFileSync(join(dir, "plan.json"), JSON.stringify({ voiceId, model: dry ? null : MODEL, total: round(total), chars, lines: record }, null, 1));
  const drift = record.reduce((a, l) => (l.drift > a.drift ? l : a));
  return {
    file,
    dry,
    voiceId,
    lines: record,
    chars,
    requested: record.filter((l) => l.source === "ElevenLabs").length,
    cached: record.filter((l) => l.source === "cache").length,
    maxTempo: Math.max(...record.map((l) => l.tempo)),
    drift,
    warnings,
  };
}
