"""Cut a long raw screen recording down to a fixed length for the demo video.

Usage (repo root):
  scripts/edit_demo.sh [raw.mov] [seconds] [out.mp4]
  defaults: data/video/demo-raw.mov, 130, data/video/demo-cut.mp4

How it works:
  1. Find idle stretches with ffmpeg freezedetect, on a small 5 fps copy of the picture.
  2. Idle stretches play fast (IDLE_SPEED, default 8x; long ones faster, so each lasts at most
     MAX_IDLE_OUT seconds). They get a small "8x" badge.
  3. Active stretches (new Slack messages, typing, scrolling) play at one speed, from 1x up to
     MAX_ACTIVE_SPEED, chosen so the cut lasts exactly the target length.
     If active time still does not fit, the script says so and the cut runs long.
  4. Each piece is scaled and padded to 1920x1080, 30 fps, then all pieces are joined.
The output has no audio. stitch_video.sh adds silence, the jingle and the voiceover.

Env knobs: IDLE_SPEED (8), MAX_IDLE_OUT (2.0 s), MAX_ACTIVE_SPEED (3.0), FREEZE_NOISE (0.003),
FREEZE_MIN (1.0 s), MIN_PIECE (0.4 s).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VDIR = ROOT / "data" / "video"

IDLE_SPEED = float(os.environ.get("IDLE_SPEED", "8"))
MAX_IDLE_OUT = float(os.environ.get("MAX_IDLE_OUT", "2.0"))
MAX_ACTIVE_SPEED = float(os.environ.get("MAX_ACTIVE_SPEED", "3.0"))
FREEZE_NOISE = os.environ.get("FREEZE_NOISE", "0.003")
FREEZE_MIN = os.environ.get("FREEZE_MIN", "1.0")
MIN_PIECE = float(os.environ.get("MIN_PIECE", "0.4"))
VF_NORM = (
    "scale=1920:1080:force_original_aspect_ratio=decrease,"
    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
)


@dataclass
class Piece:
    start: float
    end: float
    idle: bool
    speed: float = 1.0

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def out_length(self) -> float:
        return self.length / self.speed


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.stdout.strip())


def detect_idle(path: Path, total: float) -> list[tuple[float, float]]:
    vf = f"fps=5,scale=640:-2,freezedetect=n={FREEZE_NOISE}:d={FREEZE_MIN}"
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf", vf, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"freezedetect failed: {res.stderr[-500:]}")
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", res.stderr)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", res.stderr)]
    if len(ends) < len(starts):  # frozen until the end of the file
        ends.append(total)
    return list(zip(starts, ends))


def build_pieces(total: float, idle: list[tuple[float, float]]) -> list[Piece]:
    pieces: list[Piece] = []
    t = 0.0
    for s, e in idle:
        if s - t > 0:
            pieces.append(Piece(t, s, idle=False))
        pieces.append(Piece(s, e, idle=True))
        t = e
    if total - t > 0:
        pieces.append(Piece(t, total, idle=False))
    # Fold tiny pieces into the previous one, so we do not cut every few frames.
    merged: list[Piece] = []
    for p in pieces:
        if merged and (p.length < MIN_PIECE or merged[-1].idle == p.idle):
            merged[-1].end = p.end
        else:
            merged.append(p)
    return merged


def plan_speeds(pieces: list[Piece], target: float) -> float:
    """Set speeds in place. Returns the planned output length."""
    for p in pieces:
        if p.idle:
            p.speed = max(IDLE_SPEED, p.length / MAX_IDLE_OUT)
    idle_out = sum(p.out_length for p in pieces if p.idle)
    active = sum(p.length for p in pieces if not p.idle)
    room = target - idle_out
    if active <= 0:
        a = 1.0
    elif room <= 0:
        a = MAX_ACTIVE_SPEED
    else:
        a = min(max(active / room, 1.0), MAX_ACTIVE_SPEED)
    for p in pieces:
        if not p.idle:
            p.speed = a
    planned = sum(p.out_length for p in pieces)
    if planned < target - 0.05 and idle_out > 0:
        # Too short at 1x: slow the idle parts down (never below 2x) to fill the time.
        need = target - active
        scale = idle_out / need if need > 0 else 1.0
        for p in pieces:
            if p.idle:
                p.speed = max(p.speed * scale, 2.0)
        planned = sum(p.out_length for p in pieces)
    return planned


def make_badge(path: Path, label: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    w, h = 190, 72
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=18, fill=(20, 20, 20, 190))
    for x0 in (18, 44):  # two "fast forward" triangles
        d.polygon([(x0, 18), (x0, 54), (x0 + 26, 36)], fill=(255, 255, 255, 235))
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
    except OSError:
        font = ImageFont.load_default()
    d.text((84, 14), label, font=font, fill=(255, 255, 255, 235))
    img.save(path)


def render_piece(src: Path, p: Piece, out: Path, badge: Path | None) -> None:
    vf = f"setpts=(PTS-STARTPTS)/{p.speed:.4f},fps=30,{VF_NORM}"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-ss", f"{p.start:.3f}", "-t", f"{p.length:.3f}", "-i", str(src)]
    if badge:
        cmd += ["-i", str(badge), "-filter_complex", f"[0:v]{vf}[b];[b][1:v]overlay=W-w-40:40,format=yuv420p[v]",
                "-map", "[v]"]
    else:
        cmd += ["-vf", f"{vf},format=yuv420p"]
    cmd += ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30", str(out)]
    run(cmd)


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else VDIR / "demo-raw.mov"
    target = float(sys.argv[2]) if len(sys.argv) > 2 else 130.0
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else VDIR / "demo-cut.mp4"
    if not src.exists():
        print(f"error: raw recording not found: {src}", file=sys.stderr)
        return 1

    total = duration(src)
    idle = detect_idle(src, total)
    pieces = build_pieces(total, idle)
    planned = plan_speeds(pieces, target)
    idle_in = sum(p.length for p in pieces if p.idle)
    print(f"raw {total:.1f}s: {len(pieces)} pieces, idle {idle_in:.1f}s, active {total - idle_in:.1f}s")
    active_speed = next((p.speed for p in pieces if not p.idle), 1.0)
    print(f"active speed {active_speed:.2f}x, planned {planned:.1f}s, target {target:.1f}s")
    if planned > target + 0.5:
        print(f"warn: active time does not fit at {MAX_ACTIVE_SPEED}x; the cut runs "
              f"{planned - target:.1f}s long. Trim the raw file or raise MAX_ACTIVE_SPEED.", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        badges: dict[str, Path] = {}
        lst = tmp / "list.txt"
        with lst.open("w") as fh:
            for i, p in enumerate(pieces):
                if p.out_length < 1 / 30:
                    continue
                badge = None
                if p.idle:
                    label = f"{round(p.speed)}×"
                    if label not in badges:
                        badges[label] = tmp / f"badge{len(badges)}.png"
                        make_badge(badges[label], label)
                    badge = badges[label]
                part = tmp / f"p{i:04d}.mp4"
                render_piece(src, p, part, badge)
                fh.write(f"file '{part}'\n")
        out.parent.mkdir(parents=True, exist_ok=True)
        cut_to = max(target, planned) if planned > target + 0.5 else target
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(lst), "-t", f"{cut_to:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-r", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
    print(f"done: {out} ({duration(out):.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
