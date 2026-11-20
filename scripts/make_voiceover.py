"""Generate the demo voiceover with the OpenAI speech API, one mp3 per section.

Usage (repo root):
  uv run python scripts/make_voiceover.py              # all required sections
  uv run python scripts/make_voiceover.py --optional   # also the optional sponsor lines
  uv run python scripts/make_voiceover.py --print      # print the script and slots, no API call

Output: data/video/vo/<id>.mp3 and data/video/vo/manifest.tsv (id, start s, slot s, real s).
stitch_video.sh reads the manifest and places each clip at its start time.
An existing mp3 is kept; delete it to regenerate.

Env: OPENAI_API_KEY (repo .env). MARCO_TTS_MODEL (default gpt-4o-mini-tts), MARCO_TTS_VOICE (default cedar).
Cost: gpt-4o-mini-tts is $0.60 per 1M text tokens in and $12 per 1M audio tokens out.
The script prints an estimate from the text length and the audio length
(about $0.015 per audio minute, OpenAI's own estimate for this model).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
VO_DIR = ROOT / "data" / "video" / "vo"

INSTRUCTIONS = (
    "Warm, upbeat narrator with a light, playful smile in the voice, like a friendly product launch video. "
    "Clear and confident. Medium-fast pace. Short pause at each full stop. "
    "Say 'approve' with a little extra emphasis, like a catchphrase."
)

# (id, start on the final timeline in s, slot length in s, text, optional)
SECTIONS: list[tuple[str, float, float, str, bool]] = [
    (
        "01_book", 12.5, 24.0,
        "Meet Marco. Tokyo asks for a trip in Slack. "
        "Cognee remembers his habits: Courtyard Novato, room only. "
        "Senso checks the policy. "
        "TAP is sold out, and business is out of policy. Marco picks KLM: best value. "
        "Marco does the work. You keep the decision: a Statsig gate makes sure of it. "
        "One click from you is the accountability. Tokyo says: approve.",
        False,
    ),
    (
        "02_clash", 37.5, 23.0,
        "Then Marco checks its own work. The return flight leaves at nine ten. "
        "The Uber comes at ten. That does not work. "
        "Marco moves the ride to five thirty and updates the calendar. Approve. Fixed. "
        "No more sprinting through the terminal in cowboy boots.",
        False,
    ),
    (
        "02b_arcee", 53.5, 7.5,
        "The ranking tier is wired for Arcee's US-trained open-weight models, live as soon as credits land.",
        False,
    ),
    (
        "03_instead", 61.5, 23.0,
        "Plans change. A colleague goes instead. "
        "Marco finds every item of the trip on the audit trail, and proposes to cancel them. Approve. "
        "We tested Marco with Firedrill: two simulated drills, scored 99.3 and 98.8 out of 100.",
        False,
    ),
    (
        "04_january", 85.5, 24.5,
        "Now the client moves the workshop again. The news lands in the thread. Nobody tags Marco. "
        "He finds the change himself and proposes a fix, behind a Statsig feature gate. "
        "One plan for the Perk trip, the calendar, the Uber and the expenses task. Approve. Everything moves.",
        False,
    ),
    (
        "04c_arch", 105.3, 4.9,
        "Under the hood: OpenClaw, eleven partner tools, one audit trail.",
        False,
    ),
    (
        "05_proof", 110.5, 9.0,
        "Every step is on the audit trail in SingleStore, with its sources, model and cost. "
        "Amplitude tracks each step.",
        False,
    ),
    (
        "06_memory", 119.5, 18.0,
        "Cognee holds Marco's memory, and Superlinked SIE reranks it. "
        "Marco's memory is built from your connected tools: Slack, Gmail, Calendar, Drive and your knowledge base. "
        "New sources, like Jira or Telegram, plug in the same way.",
        False,
    ),
    (
        "07_vision", 137.8, 30.5,
        "We built Marco today for this hackathon. Starting today, we use it at our company for every Perk trip. "
        "A cloud copy of Marco runs on Guild, with keys held by Guild. "
        "Travel is Marco's first skill. The same core runs any task you delegate: "
        "memory, policy, your decision, and a full audit trail. "
        "We enable people. We do not replace them. "
        "Built in one day with Cursor, spec-driven and verified with the tribunal method.",
        False,
    ),
    # Optional lines: generate with --optional. Add them to the edit only if the feature is wired.
    ("opt_arcee", 0.0, 5.0, "Ranking runs on Arcee's Trinity, a US-trained open-weight model.", True),
]

TEXT_PRICE_PER_TOKEN = 0.60 / 1_000_000
USD_PER_AUDIO_MIN = 0.015


def duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--optional", action="store_true", help="also generate the optional sponsor lines")
    ap.add_argument("--print", dest="print_only", action="store_true", help="print the script only")
    args = ap.parse_args()

    sections = [s for s in SECTIONS if args.optional or not s[4]]
    if args.print_only:
        for sid, start, slot, text, opt in sections:
            print(f"[{sid}] start {start:.1f}s slot {slot:.0f}s{' OPTIONAL' if opt else ''}\n{text}\n")
        return 0

    load_dotenv(ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY is not set in .env", file=sys.stderr)
        return 2
    model = os.environ.get("MARCO_TTS_MODEL", "gpt-4o-mini-tts")
    voice = os.environ.get("MARCO_TTS_VOICE", "cedar")
    VO_DIR.mkdir(parents=True, exist_ok=True)

    rows, total_audio, new_audio, total_chars, over = [], 0.0, 0.0, 0, []
    with httpx.Client(
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        headers={"Authorization": f"Bearer {key}"},
        timeout=120,
    ) as client:
        for sid, start, slot, text, opt in sections:
            out = VO_DIR / f"{sid}.mp3"
            fresh = not out.exists()
            if fresh:
                r = client.post(
                    "/audio/speech",
                    json={"model": model, "voice": voice, "input": text,
                          "instructions": INSTRUCTIONS, "response_format": "mp3"},
                )
                if r.is_error:
                    print(f"error: {sid}: {r.status_code} {r.text[:300]}", file=sys.stderr)
                    return 1
                out.write_bytes(r.content)
                total_chars += len(text) + len(INSTRUCTIONS)
            real = duration_s(out)
            total_audio += real
            new_audio += real if fresh else 0.0
            flag = "  OVER SLOT" if real > slot else ""
            if real > slot:
                over.append(sid)
            print(f"{sid}: {real:5.1f}s / slot {slot:4.1f}s{flag}")
            if not opt:
                rows.append(f"{sid}\t{start}\t{slot}\t{real:.2f}")

    (VO_DIR / "manifest.tsv").write_text("id\tstart\tslot\treal\n" + "\n".join(rows) + "\n")
    text_usd = (total_chars / 4) * TEXT_PRICE_PER_TOKEN
    audio_usd = new_audio / 60 * USD_PER_AUDIO_MIN
    print(f"\naudio {total_audio:.1f}s. Estimated cost this run: ${text_usd + audio_usd:.4f} "
          f"(text ${text_usd:.4f} + audio ${audio_usd:.4f}; kept files cost $0)")
    if over:
        print(f"warn: over slot: {', '.join(over)}. Shorten the text, delete the mp3 and re-run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
