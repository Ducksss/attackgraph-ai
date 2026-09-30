#!/usr/bin/env bash
# Review helper: tile frames of a clip at the given times (seconds) into one image, 2 per row.
# usage: scripts/video/peek.sh build/video/clips/03.mp4 out.jpg 0.5 4 8 [...]
# ffmpeg comes from PATH unless FFMPEG names the binary.
set -euo pipefail
ff="${FFMPEG:-ffmpeg}"
clip="$1"; out="$2"; shift 2
tmp=$(mktemp -d "${TMPDIR:-/tmp}/peek.XXXX")
i=0
for t in "$@"; do
  "$ff" -hide_banner -loglevel error -y -ss "$t" -i "$clip" -frames:v 1 -vf "scale=960:540:flags=lanczos" "$tmp/$(printf %02d $i).png"
  i=$((i+1))
done
n=$i
if [ $((n % 2)) -eq 1 ]; then "$ff" -hide_banner -loglevel error -y -f lavfi -i color=c=black:s=960x540 -frames:v 1 "$tmp/$(printf %02d $n).png"; n=$((n+1)); fi
rows=$((n / 2))
"$ff" -hide_banner -loglevel error -y -framerate 1 -i "$tmp/%02d.png" -vf "tile=2x${rows}:padding=6:color=white" -frames:v 1 -q:v 3 "$out"
rm -rf "$tmp"
echo "$out"
