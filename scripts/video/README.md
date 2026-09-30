# Demo video pipeline

These scripts rebuild the captioned demo video from the real pages. Headless Chrome drives each page frame by frame over the DevTools protocol, and ffmpeg encodes the frames into one clip per shot. Captions and the title and end cards are rendered in Chrome and laid over the clips. The result is a 1920 x 1080, 30 fps H.264 video with a silent AAC track, about 2 minutes 28 seconds long.

Everything goes to `build/video/` at the repo root, or to `--out DIR`:

| Path | What it is |
|---|---|
| `attackgraph-ai-demo.mp4` | The video |
| `attackgraph-ai-demo.srt` | The captions as subtitles |
| `contact-sheet.png` | One labelled frame per shot |
| `shots.md` | The shot list: times, sources and captions |
| `clips/` | One clip and manifest per shot, and the two cards |
| `captions/`, `cards/` | Rendered caption strips and card images |
| `logs/` | The Bedrock press log and replies, the ffmpeg filter graph, thumbnails |

Frames are piped straight into ffmpeg and not kept. The record of the submitted cut, recorded on 30 September 2026, is in [`docs/video/`](../../docs/video/).

## Prerequisites

* Node 22 or newer. The scripts use its built-in WebSocket and need no npm packages.
* Google Chrome or Chromium. The scripts use `CHROME` if set, then the standard macOS install, then `google-chrome` or `chromium` on PATH.
* ffmpeg built with libx264, and ffprobe, from PATH or `FFMPEG` and `FFPROBE`. libass and freetype are not needed.
* Network access to the hosted site, GitHub and Google Fonts.
* For shots 4 to 8, the local app. From the repo root:

```bash
.venv/bin/streamlit run app.py --server.headless true --server.port 8599 --server.address 127.0.0.1
```

Set `APP_URL` if it runs somewhere else (the default is `http://127.0.0.1:8599`). Shot 7's live take also needs the app's AWS credentials (see [Amazon Bedrock](../../README.md#amazon-bedrock)); the scripts never read them.

## Commands

Run from the repo root:

```bash
node scripts/video/make.mjs                 # assemble from the clips already in build/video/clips/
node scripts/video/make.mjs 3 9             # re-shoot shots 3 and 9, then assemble
node scripts/video/make.mjs 0 10            # re-render the title card (0) and end card (10), then assemble
node scripts/video/make.mjs all             # re-shoot every shot except 7, then assemble
node scripts/video/make.mjs 7 --recorded    # shot 7 from the hosted demo's recorded AI reply
node scripts/video/make.mjs 7 --live        # shot 7 with one live Amazon Bedrock call
node scripts/video/make.mjs 7 --dry         # rehearse shot 7 without pressing the button
```

A first build needs every clip: `node scripts/video/make.mjs all 7 --recorded`, or `--live` in place of `--recorded`. `--out DIR` writes everything under `DIR` instead of `build/video/`, and `--no-assemble` shoots without assembling. To review a take, `scripts/video/peek.sh CLIP OUT.jpg T1 T2 ...` tiles the clip's frames at the given times into one image.

## The Bedrock press cap

Shot 7 presses **Explain with Amazon Bedrock** only with `--live`. Each press is one chargeable Converse call to Amazon Nova Pro. Every press is logged in `logs/bedrock-presses.jsonl` under the output directory, and make.mjs refuses a fourth. Each reply is saved beside it as `logs/bedrock-reply-*.json`. If a press shows "AI explanation unavailable", the take stops: use `--recorded`, which shows the hosted demo's recorded reply with its date and request ID.

## Captions

Caption text is in [`captions.json`](captions.json), and each shot in [`shots.mjs`](shots.mjs) marks where its captions start. Every assembly checks each caption: at most 14 words, at least 2.5 seconds on screen, at most 3 words per second, and at most 2 lines. A caption over 2 lines stops the build; the others are reported by name. A shot holds each caption long enough for its text when it is shot, so a longer caption needs that shot re-shot.

## Where each shot comes from

| Shot | Source |
|---|---|
| 0 | Title card, [`cards/title.html`](cards/title.html), with the mark from [`docs/brand/`](../../docs/brand/) |
| 1 | GitHub, signed out: the Files changed tab of [PR #3](https://github.com/Ducksss/attackgraph-ai/pull/3) |
| 2 | GitHub, signed out: the summary page of the PR's latest check run, run 36677079723 (set in `shots.mjs`) |
| 3 | Hosted site, overview: the hero |
| 4 to 8 | Local app, `/demo`: the pull request, the path, the conditions, the live Bedrock explanation and the fix |
| 9 | Hosted site, overview: trust and limits |
| 10 | End card, [`cards/end.html`](cards/end.html) |

Shots 3 and 9 are the ones to re-shoot after the overview is redeployed. Shot 7's `--recorded` variant comes from the hosted demo page.

## Known quirks

* While PR #3 has two failing runs of the check, its Files changed tab shows the check's note on line 27 twice.
* Signed out, the Checks tab does not expand its annotations, so shot 2 uses the run's summary page, which shows the failed AttackGraph AI job and the note's title.
* GitHub avatars are hidden with CSS, so nothing personal is on screen.
* Streamlit's hover tooltips are hidden with CSS. Each frame takes real time to capture, so the drawn cursor dwells on buttons long enough to open them.
* Each run uses a fresh signed-out Chrome profile in the system temp directory, deleted afterwards.
