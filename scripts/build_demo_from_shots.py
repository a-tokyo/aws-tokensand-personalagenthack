"""Build the demo middle section (data/video/demo-cut.mp4) from still screenshots.

Usage (repo root):
  uv run python scripts/build_demo_from_shots.py [--preview]

Each shot is a still image with a slow pan/zoom (Ken Burns). Shots join with short crossfades.
Cut times follow data/video/vo/manifest.tsv: the timeline here starts at 0 = the end of the intro
(12 s on the final video). The section length is LENGTH seconds.
Missing images become a plain title card, so the build never stops on a missing shot.
Images live in data/video/shots/. Cards (sources, core) are drawn here with Pillow.
--preview renders at 960x540 with a fast preset.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
VDIR = ROOT / "data" / "video"
SHOTS = VDIR / "shots"
INTRO = 12.0          # the intro length on the final video
LENGTH = 156.0        # this section: 0:12 to 2:43.5
XFADE = 0.35
FONT = "/System/Library/Fonts/Helvetica.ttc"
BG = (18, 20, 28)

# Rect = (centre x, centre y, width), all as fractions of the 16:9 canvas.
FULL = (0.5, 0.5, 1.0)


@dataclass
class Shot:
    at: float                  # cut-in time on the final video (s)
    image: str                 # file in shots/, or "card:<name>"
    start: tuple = FULL        # rect at the start
    end: tuple = FULL          # rect at the end
    crop: tuple | None = None  # pre-crop box in source pixels (x0, y0, x1, y1)
    title: str = ""            # fallback card text if the image is missing


# Slack shots slack_01.jpg ... come from the live thread. Until they exist, a title card shows.
SHOT_LIST: list[Shot] = [
    # Beat 01: booking from a Slack thread (12.5 s - 36.5 s)
    Shot(12.0, "slack_01.jpg", (0.5, 0.28, 0.5), (0.5, 0.62, 0.5), title="01  Book a trip from Slack"),
    Shot(18.0, "slack_02.jpg", (0.5, 0.28, 0.5), (0.5, 0.62, 0.5), title="Marco remembers your habits"),
    Shot(24.5, "perk_1.jpg", (0.4, 0.5, 0.9), (0.3, 0.55, 0.6), title="KLM: best value, in policy"),
    Shot(30.5, "slack_03.jpg", (0.5, 0.28, 0.5), (0.5, 0.62, 0.5), title="You keep the decision: approve"),
    # Beat 02: clash (37.5 s - 61 s)
    Shot(37.0, "slack_04.jpg", (0.5, 0.28, 0.5), (0.5, 0.62, 0.5), title="02  Marco finds a clash"),
    Shot(44.0, "audit_tall.png", (0.5, 0.5, 1.0), (0.45, 0.6, 0.8), crop=(560, 3400, 2640, 3900),
         title="Flight 09:10. Uber 10:00."),
    Shot(51.0, "uber_1.jpg", (0.5, 0.5, 1.0), (0.42, 0.5, 0.7), crop=(380, 100, 2760, 680),
         title="Ride moved to 05:30"),
    Shot(56.5, "slack_05.jpg", (0.5, 0.28, 0.5), (0.5, 0.62, 0.5), title="Approve. Fixed."),
    # Beat 03: someone else goes (61.5 s - 85 s)
    Shot(61.0, "slack_06.jpg", (0.5, 0.22, 0.5), (0.5, 0.36, 0.5), title="03  Someone else goes instead"),
    Shot(68.5, "slack_07.jpg", (0.5, 0.4, 0.5), (0.5, 0.62, 0.5), title="Cancel everything? Approve."),
    Shot(74.5, "firedrill_1.jpg", (0.5, 0.5, 1.0), (0.32, 0.55, 0.45), title="Firedrill: 99.3 and 98.8"),
    # Beat 04: the workshop moves; Marco finds the change himself (85.5 s - 110 s)
    Shot(85.0, "slack_11.jpg", (0.5, 0.2, 0.5), (0.5, 0.36, 0.5), title="04  Nobody tags Marco"),
    Shot(92.0, "slack_12.jpg", (0.5, 0.22, 0.5), (0.5, 0.36, 0.5), title="Marco finds the change himself"),
    Shot(97.5, "statsig_1.jpg", (0.5, 0.5, 1.0), (0.3, 0.35, 0.55), title="Statsig gate: proactive_mode"),
    Shot(99.5, "slack_09.jpg", (0.5, 0.3, 0.5), (0.5, 0.5, 0.5), title="One plan. Approve."),
    Shot(102.3, "slack_10.jpg", (0.5, 0.2, 0.5), (0.5, 0.26, 0.42), title="Approve. Everything moves."),
    Shot(105.0, "architecture.png", (0.5, 0.5, 1.0), (0.5, 0.48, 0.8), title="Architecture"),
    # Proof: audit trail (110.5 s - 119 s)
    Shot(110.0, "audit_tall.png", (0.5, 0.5, 1.0), (0.45, 0.45, 0.75), crop=(520, 2160, 2680, 3375),
         title="Every step on the audit trail"),
    # Memory (119.5 s - 138 s)
    Shot(119.0, "cognee_1.jpg", FULL, (0.45, 0.42, 0.6), title="Cognee memory"),
    Shot(124.0, "cognee_3.jpg", (0.6, 0.5, 0.8), (0.65, 0.55, 0.45), title="Cognee memory"),
    Shot(128.0, "card:sources", FULL, (0.5, 0.5, 0.92)),
    Shot(133.5, "obsidian_1.png", FULL, (0.6, 0.5, 0.7), title="Knowledge base"),
    # Vision (138.5 s - 168 s)
    Shot(138.0, "card:today", FULL, (0.5, 0.5, 0.92)),
    Shot(143.5, "guild_1.jpg", (0.5, 0.4, 1.0), (0.42, 0.3, 0.6), title="Marco on Guild"),
    Shot(147.0, "card:core", FULL, (0.5, 0.5, 0.9)),
    Shot(153.0, "card:people", FULL, (0.5, 0.5, 0.92)),
    Shot(159.5, "card:built", FULL, (0.5, 0.5, 0.92)),
]


def font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def card(lines: list[tuple[str, int, tuple]], out: Path) -> None:
    img = Image.new("RGB", (3840, 2160), BG)
    d = ImageDraw.Draw(img)
    total = sum(s + 60 for _, s, _ in lines)
    y = (2160 - total) // 2
    for text, size, colour in lines:
        f = font(size)
        w = d.textlength(text, font=f)
        d.text(((3840 - w) / 2, y), text, font=f, fill=colour)
        y += size + 60
    img.save(out)


WHITE, MUTED, ACCENT = (240, 240, 245), (150, 155, 170), (196, 160, 90)
CARDS = {
    "sources": [("Memory from your connected tools", 120, WHITE),
                ("Slack  ·  Gmail  ·  Calendar  ·  Drive  ·  Knowledge base", 96, ACCENT),
                ("Plug in next: Jira  ·  Telegram", 80, MUTED)],
    "today": [("Built today for this hackathon.", 130, WHITE),
              ("From today: every Perk trip at our company.", 96, ACCENT)],
    "core": [("Travel is Marco's first skill.", 120, WHITE),
             ("Memory  ·  Policy  ·  Your decision  ·  Audit trail", 96, ACCENT),
             ("The same core runs any task you delegate.", 80, MUTED)],
    "people": [("We enable people.", 150, WHITE), ("We do not replace them.", 150, ACCENT)],
    "built": [("Built in one day with Cursor", 120, WHITE),
              ("Spec-driven  ·  verified with the tribunal method", 90, ACCENT),
              ("Cognee · Senso · SingleStore · Statsig · Amplitude · Firedrill · Superlinked", 64, MUTED)],
}


def canvas(src: Path, crop: tuple | None, out: Path) -> None:
    """Fit the image (optionally pre-cropped) onto a 3840x2160 canvas."""
    img = Image.open(src).convert("RGB")
    if crop:
        img = img.crop(crop)
    img.thumbnail((3840, 2160), Image.LANCZOS)
    if img.width < 3840 and img.height < 2160:  # upscale small images
        k = min(3840 / img.width, 2160 / img.height)
        img = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
    bg = Image.new("RGB", (3840, 2160), BG)
    bg.paste(img, ((3840 - img.width) // 2, (2160 - img.height) // 2))
    bg.save(out)


def render(still: Path, shot: Shot, length: float, out: Path, size: tuple[int, int], fast: bool) -> None:
    frames = max(int(round(length * 30)), 1)
    (cx0, cy0, w0), (cx1, cy1, w1) = shot.start, shot.end
    # Smoothstep easing on the frame index.
    p = f"(on/{max(frames - 1, 1)})"
    e = f"({p}*{p}*(3-2*{p}))"
    w = f"({w0}+({w1}-{w0})*{e})"
    cx = f"({cx0}+({cx1}-{cx0})*{e})"
    cy = f"({cy0}+({cy1}-{cy0})*{e})"
    z = f"1/{w}"
    x = f"max(0,min(iw-iw/zoom,iw*{cx}-iw/zoom/2))"
    y = f"max(0,min(ih-ih/zoom,ih*{cy}-ih/zoom/2))"
    vf = (f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={size[0]}x{size[1]}:fps=30,"
          "setsar=1,format=yuv420p")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "30",
         "-t", f"{length:.3f}", "-i", str(still), "-vf", vf, "-frames:v", str(frames),
         "-c:v", "libx264", "-preset", "ultrafast" if fast else "medium", "-crf", "18", str(out)],
        check=True,
    )


def main() -> int:
    fast = "--preview" in sys.argv
    size = (960, 540) if fast else (1920, 1080)
    out = VDIR / ("demo-cut-preview.mp4" if fast else "demo-cut.mp4")
    end = INTRO + LENGTH
    shots = sorted(SHOT_LIST, key=lambda s: s.at)
    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        clips: list[tuple[Path, float]] = []
        for i, s in enumerate(shots):
            nxt = shots[i + 1].at if i + 1 < len(shots) else end
            length = (nxt - s.at) + (XFADE if i + 1 < len(shots) else 0.0)
            if i == 0:
                length += 0.0
            still = tmp / f"still{i:02d}.png"
            if s.image.startswith("card:"):
                card(CARDS[s.image[5:]], still)
            elif (SHOTS / s.image).exists():
                canvas(SHOTS / s.image, s.crop, still)
            else:
                print(f"missing {s.image}: title card '{s.title}'")
                card([(s.title or s.image, 130, WHITE)], still)
            clip = tmp / f"clip{i:02d}.mp4"
            render(still, s, length, clip, size, fast)
            clips.append((clip, s.at - INTRO))
        # Crossfade chain. Cut i happens at (shot.at - INTRO) on this section's timeline.
        inputs: list[str] = []
        for c, _ in clips:
            inputs += ["-i", str(c)]
        chain, last = [], "[0:v]"
        for i in range(1, len(clips)):
            offset = clips[i][1] - clips[0][1]
            label = f"[x{i}]"
            chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}{label}")
            last = label
        graph = ";".join(chain) if chain else "[0:v]null[x0]"
        last = last if chain else "[x0]"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
             "-map", last, "-t", f"{LENGTH:.3f}", "-r", "30", "-c:v", "libx264",
             "-preset", "ultrafast" if fast else "medium", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(out)],
            check=True,
        )
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(out)], capture_output=True, text=True, check=True).stdout.strip()
    print(f"done: {out} ({float(dur):.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
