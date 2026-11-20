#!/usr/bin/env bash
# Stitch the demo video: intro.mp4 + screen recording + outro.mp4, then add captions.
#
# Usage (repo root):
#   scripts/stitch_video.sh <screen-recording> [output.mp4]
#
# Inputs (data/video/): intro.mp4 and outro.mp4 are optional; a missing one is skipped.
# captions.srt is timed for a 12 s intro (CAPTION_INTRO_S). The script shifts it by the real
# intro length (0 if there is no intro), and drops cues that end before 0:00.
# Voiceover: data/video/vo/manifest.tsv (from scripts/make_voiceover.py) places each mp3 on the
# timeline; the intro, screen and outro audio duck under it. MARCO_NO_VO=1 skips it.
# Each part is normalised to 1920x1080, 30 fps, yuv420p, square pixels, AAC 48 kHz stereo.
# A part without an audio track gets silence, so the concat stays in sync.
# Captions are burned in when ffmpeg has the `subtitles` filter (libass).
# Otherwise they go in as a soft subtitle track, with a warning.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VDIR="${MARCO_VIDEO_DIR:-$ROOT/data/video}"
SCREEN="${1:?usage: scripts/stitch_video.sh <screen-recording> [output.mp4]}"
OUT="${2:-$VDIR/marco-demo.mp4}"
[[ "$OUT" = /* ]] || OUT="$PWD/$OUT"
SRT="${MARCO_CAPTIONS:-$VDIR/captions.srt}"

# Prefer Homebrew's keg-only ffmpeg-full (it has libass) when it is installed.
for d in /opt/homebrew/opt/ffmpeg-full/bin /usr/local/opt/ffmpeg-full/bin; do
  [[ -x "$d/ffmpeg" ]] && PATH="$d:$PATH" && break
done
command -v ffmpeg >/dev/null || { echo "error: ffmpeg is not installed (brew install ffmpeg)" >&2; exit 1; }
command -v ffprobe >/dev/null || { echo "error: ffprobe is not installed" >&2; exit 1; }
[[ -f "$SCREEN" ]] || { echo "error: screen recording not found: $SCREEN" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

VF="scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
ENC=(-c:v libx264 -preset medium -crf 20 -c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart)

has_audio() {
  [[ -n "$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$1")" ]]
}

normalise() { # <in> <out>
  if has_audio "$1"; then
    ffmpeg -hide_banner -loglevel error -y -i "$1" -vf "$VF" "${ENC[@]}" "$2"
  else
    ffmpeg -hide_banner -loglevel error -y -i "$1" \
      -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
      -map 0:v:0 -map 1:a:0 -shortest -vf "$VF" "${ENC[@]}" "$2"
  fi
}

: > "$TMP/list.txt"
CAPTION_INTRO_S="${CAPTION_INTRO_S:-12}"
intro_s=0
[[ -f "$VDIR/intro.mp4" ]] && intro_s="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VDIR/intro.mp4")"

i=0
for part in "$VDIR/intro.mp4" "$SCREEN" "$VDIR/outro.mp4"; do
  if [[ ! -f "$part" ]]; then
    echo "skip: $part not found"
    continue
  fi
  i=$((i + 1))
  echo "normalise $i: $part"
  normalise "$part" "$TMP/part$i.mp4"
  echo "file '$TMP/part$i.mp4'" >> "$TMP/list.txt"
done

ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$TMP/list.txt" -c copy "$TMP/joined.mp4"

# Voiceover: place each clip from vo/manifest.tsv at its start time (timed for a 12 s intro,
# shifted like the captions). The other audio ducks under the voice (sidechain compression).
VO_DIR="${MARCO_VO_DIR:-$VDIR/vo}"
VO_MANIFEST="$VO_DIR/manifest.tsv"
if [[ "${MARCO_NO_VO:-0}" != 1 && -f "$VO_MANIFEST" ]]; then
  inputs=(-i "$TMP/joined.mp4")
  filt=""
  labels=""
  n=0
  while IFS=$'\t' read -r id start _slot _real; do
    [[ "$id" == id || -z "$id" ]] && continue
    clip="$VO_DIR/$id.mp3"
    [[ -f "$clip" ]] || { echo "warn: missing $clip; skipped" >&2; continue; }
    ms="$(awk -v s="$start" -v a="$intro_s" -v b="$CAPTION_INTRO_S" 'BEGIN { v = (s + a - b) * 1000; if (v < 0) v = 0; printf "%d", v }')"
    n=$((n + 1))
    inputs+=(-i "$clip")
    filt+="[$n:a]aresample=48000,aformat=channel_layouts=stereo,adelay=${ms}|${ms}[vo$n];"
    labels+="[vo$n]"
  done < "$VO_MANIFEST"
  if (( n > 0 )); then
    filt+="${labels}amix=inputs=$n:normalize=0:duration=longest,volume=1.6,asplit=2[vo][sc];"
    filt+="[0:a][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bed];"
    filt+="[bed][vo]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[aout]"
    ffmpeg -hide_banner -loglevel error -y "${inputs[@]}" -filter_complex "$filt" \
      -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k -ar 48000 "$TMP/voiced.mp4"
    mv "$TMP/voiced.mp4" "$TMP/joined.mp4"
    echo "voiceover mixed: $n clips"
  fi
fi

# Shift the SRT so it matches the real intro length.
shift_srt() { # <in> <out> <shift seconds>
  awk -v sh="$3" '
    function t2s(t,  a) { split(t, a, /[:,]/); return a[1]*3600 + a[2]*60 + a[3] + a[4]/1000 }
    function s2t(x,  ms) { ms = int(x*1000 + 0.5); return sprintf("%02d:%02d:%02d,%03d", int(ms/3600000), int(ms/60000)%60, int(ms/1000)%60, ms%1000) }
    BEGIN { RS = ""; FS = "\n"; n = 0 }
    {
      split($2, tt, / --> /); a = t2s(tt[1]) + sh; b = t2s(tt[2]) + sh
      if (b <= 0) next
      if (a < 0) a = 0
      n++; printf "%d\n%s --> %s\n", n, s2t(a), s2t(b)
      for (k = 3; k <= NF; k++) print $k
      print ""
    }' "$1" > "$2"
}

mkdir -p "$(dirname "$OUT")"
if [[ -f "$SRT" ]]; then
  shift_s="$(awk -v a="$intro_s" -v b="$CAPTION_INTRO_S" 'BEGIN { printf "%.3f", a - b }')"
  shift_srt "$SRT" "$TMP/captions.srt" "$shift_s"
  echo "captions shifted by ${shift_s} s (intro ${intro_s} s)"
fi
FILTERS="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"

if [[ ! -f "$SRT" ]]; then
  echo "warn: no captions at $SRT; output has no captions" >&2
  cp "$TMP/joined.mp4" "$OUT"
elif grep -qE '^ *[A-Z.]+ +subtitles ' <<< "$FILTERS"; then
  # Run inside $TMP so the filter gets a plain path (no escaping problems).
  (cd "$TMP" && ffmpeg -hide_banner -loglevel error -y -i joined.mp4 \
    -vf "subtitles=captions.srt:force_style='FontName=Helvetica,FontSize=22,Outline=2,MarginV=40'" \
    -c:v libx264 -preset medium -crf 20 -c:a copy -movflags +faststart "$OUT")
  echo "captions burned in"
else
  echo "warn: this ffmpeg has no 'subtitles' filter (needs libass); adding a soft subtitle track" >&2
  echo "      to burn in: brew install ffmpeg-full, then re-run" >&2
  ffmpeg -hide_banner -loglevel error -y -i "$TMP/joined.mp4" -i "$TMP/captions.srt" \
    -map 0 -map 1 -c:v copy -c:a copy -c:s mov_text -metadata:s:s:0 language=eng \
    -disposition:s:0 default -movflags +faststart "$OUT"
fi

dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")"
echo "done: $OUT (${dur%.*} s)"
