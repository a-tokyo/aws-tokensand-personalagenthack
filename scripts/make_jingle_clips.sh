#!/usr/bin/env bash
# Cut the cold open (intro.mp4, 12 s) and the outro (outro.mp4, 8 s) from the jingle track.
#
# Usage (repo root):
#   scripts/make_jingle_clips.sh [jingle.mp4]     # default data/video/jingle_full.mp4
#
# The jingle comes from Gemini "Create music" (a 1024x1024 cover image + the sung track).
# Lyric timing in that file (from its own subtitle track):
#   21.8 s "But Marco found a flight..."   26.2 s chorus   52.4 s chorus again
# Override the cut points with INTRO_AT / OUTRO_AT if a new take has other timings.
# Picture: the cover art, centred on a blurred copy of itself, with a slow zoom. 1920x1080, 30 fps.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VDIR="${MARCO_VIDEO_DIR:-$ROOT/data/video}"
SRC="${1:-$VDIR/jingle_full.mp4}"
INTRO_AT="${INTRO_AT:-23.9}"   # 12 s: last verse line, then the chorus
OUTRO_AT="${OUTRO_AT:-52.4}"   # 8 s: the chorus hook
[[ -f "$SRC" ]] || { echo "error: jingle not found: $SRC" >&2; exit 1; }
AVATAR="${AVATAR:-$ROOT/agent/workspace/avatar.png}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
# Marco's avatar as a round badge (Pillow from the project env). Skipped if the file is missing.
if [[ -f "$AVATAR" ]]; then
  (cd "$ROOT" && uv run --quiet python - "$AVATAR" "$TMP/avatar.png" <<'PY'
import sys
from PIL import Image, ImageDraw
img = Image.open(sys.argv[1]).convert("RGBA").resize((360, 360), Image.LANCZOS)
mask = Image.new("L", (360, 360), 0)
ImageDraw.Draw(mask).ellipse((0, 0, 359, 359), fill=255)
out = Image.new("RGBA", (380, 380), (0, 0, 0, 0))
ring = ImageDraw.Draw(out)
ring.ellipse((0, 0, 379, 379), fill=(240, 220, 170, 255))
out.paste(img, (10, 10), mask)
out.save(sys.argv[2])
PY
  ) 2>/dev/null || true
fi

clip() { # <start> <seconds> <fade-in> <out>
  local start="$1" len="$2" fin="$3" out="$4"
  local frames=$((len * 30))
  local fo_v fo_a
  fo_v=$(awk -v l="$len" 'BEGIN { print l - 0.6 }')
  fo_a=$(awk -v l="$len" 'BEGIN { print l - 1.2 }')
  local av_in=() av_f="[v0]null[v]"
  if [[ -f "$TMP/avatar.png" ]]; then
    av_in=(-loop 1 -i "$TMP/avatar.png")
    av_f="[1:v]format=rgba,fade=t=in:st=0.6:d=0.6:alpha=1[av];[v0][av]overlay=x=W-w-90:y=H-h-90:shortest=1,format=yuv420p[v]"
  fi
  ffmpeg -hide_banner -loglevel error -y -ss "$start" -t "$len" -i "$SRC" "${av_in[@]}" \
    -filter_complex "
      [0:v]fps=30,split[a][b];
      [a]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=30:2,eq=brightness=-0.15[bg];
      [b]scale=1000:1000,zoompan=z='1+0.06*on/${frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1000x1000:fps=30[fg];
      [bg][fg]overlay=(W-w)/2:(H-h)/2,fade=t=in:st=0:d=0.4,fade=t=out:st=${fo_v}:d=0.6,setsar=1,format=yuv420p[v0];
      ${av_f};
      [0:a]afade=t=in:st=0:d=${fin},afade=t=out:st=${fo_a}:d=1.2,aresample=48000[au]" \
    -map "[v]" -map "[au]" -c:v libx264 -preset medium -crf 18 -c:a aac -b:a 192k -ac 2 \
    -movflags +faststart "$out"
  echo "wrote $out"
}

clip "$INTRO_AT" 12 0.3 "$VDIR/intro.mp4"
clip "$OUTRO_AT" 8 0.1 "$VDIR/outro.mp4"
