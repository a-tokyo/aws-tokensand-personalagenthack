"""Generate the AI cold open and outro for the demo video with the OpenAI Videos API.

Usage (repo root):
  uv run python scripts/make_intro.py            # dry run: prints prompts and the cost estimate
  uv run python scripts/make_intro.py --yes      # spends money: generates and downloads the mp4s

Output: data/video/intro.mp4 and data/video/outro.mp4.

Status: OpenAI shut down the Videos API and the sora-2 models on 2026-09-24.
The script checks the endpoint with a free GET before any paid POST, and stops if it is gone.
Only run --yes with Tokyo's spend approval.

Env (from the repo .env):
  OPENAI_API_KEY      required
  MARCO_VIDEO_MODEL   default sora-2-pro
  MARCO_VIDEO_SIZE    default 1920x1080
  MARCO_VIDEO_PRICE   USD per second for the cost estimate, default 0.70
                      (the last published sora-2-pro 1080p price)
  OPENAI_BASE_URL     default https://api.openai.com/v1
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "video"

STYLE = (
    "Animated 2D cartoon, warm sunset palette, bold outlines, playful country-western style, 16:9."
)

CLIPS: list[dict[str, str]] = [
    {
        "name": "intro",
        "seconds": "12",
        "prompt": STYLE
        + " A tired young consultant in a suit and cowboy boots sits on a rolling suitcase in a busy"
        " airport. His laptop shows a chat app with a pop-up: 'You're due in Novato'. A departures"
        " board flips one row to SOLD OUT, and he droops comically. A friendly animated"
        " travel-explorer character, Marco, appears: a small compass with a wide-brimmed explorer"
        " hat, a tiny map scroll and big kind eyes. He tips his hat, taps the laptop, and paper"
        " planes, a hotel key and a calendar page swirl around the consultant like a lasso. The"
        " consultant presses a big green button labelled APPROVE. Confetti. Camera: slow push-in,"
        " then a quick whip-pan to Marco winking. Audio: upbeat country two-step, steel guitar,"
        " light harmonica. A warm male country voice sings clearly: 'Got a Slack at five, you're"
        " due in Novato by nine... Oh Marco, Marco, you just say approve!' Ends on a held smile.",
    },
    {
        "name": "outro",
        "seconds": "8",
        "prompt": STYLE
        + " Golden-hour desert highway. The consultant rides away on his rolling suitcase like a"
        " horse, laptop under his arm, and Marco the compass character with the explorer hat sits"
        " on his shoulder. A long ribbon of paper unrolls behind them like a trail of tidy receipts"
        " with check marks. In the final 2 seconds they stop, turn and tip their hats to camera,"
        " and the sky clears for a title. Audio: the same country two-step. A warm male country"
        " voice sings the hook: 'Oh Marco, Marco... just say approve!' One final steel guitar"
        " slide. No on-screen text.",
    },
]

TERMINAL_OK = {"completed"}
TERMINAL_FAIL = {"failed", "cancelled", "expired"}


class VideoApiError(RuntimeError):
    """The Videos API is unavailable or a generation failed."""


def estimate_usd(price_per_second: float) -> float:
    return sum(int(c["seconds"]) for c in CLIPS) * price_per_second


def preflight(client: httpx.Client) -> None:
    """Free GET. Stops before any paid call if the endpoint is gone or the key is bad."""
    r = client.get("/videos", params={"limit": 1})
    if r.status_code == 404:
        raise VideoApiError(
            "GET /videos returned 404: the Videos API is not available (shut down 2026-09-24). "
            "Pick another provider with Tokyo, or use Plan B in data/video/storyboard.md."
        )
    if r.status_code in (401, 403):
        raise VideoApiError(f"GET /videos returned {r.status_code}: check OPENAI_API_KEY access.")
    r.raise_for_status()


def generate(client: httpx.Client, model: str, size: str, clip: dict[str, str]) -> Path:
    out = OUT_DIR / f"{clip['name']}.mp4"
    if out.exists():
        print(f"skip {clip['name']}: {out} exists (delete it to regenerate)")
        return out
    r = client.post(
        "/videos",
        json={"model": model, "prompt": clip["prompt"], "seconds": clip["seconds"], "size": size},
    )
    if r.is_error:
        raise VideoApiError(f"create {clip['name']} failed: {r.status_code} {r.text[:300]}")
    video_id = r.json()["id"]
    print(f"{clip['name']}: job {video_id} queued")

    deadline = time.monotonic() + 20 * 60
    while True:
        job = client.get(f"/videos/{video_id}").raise_for_status().json()
        status = job.get("status")
        if status in TERMINAL_OK:
            break
        if status in TERMINAL_FAIL:
            raise VideoApiError(f"{clip['name']}: job {video_id} ended {status}: {job.get('error')}")
        if time.monotonic() > deadline:
            raise VideoApiError(f"{clip['name']}: job {video_id} timed out (last status {status})")
        print(f"{clip['name']}: {status} {job.get('progress', '')}")
        time.sleep(10)

    with client.stream("GET", f"/videos/{video_id}/content") as resp:
        resp.raise_for_status()
        tmp = out.with_suffix(".part")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
        tmp.replace(out)
    print(f"{clip['name']}: saved {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="spend money: generate the clips")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    model = os.environ.get("MARCO_VIDEO_MODEL", "sora-2-pro")
    size = os.environ.get("MARCO_VIDEO_SIZE", "1920x1080")
    price = float(os.environ.get("MARCO_VIDEO_PRICE", "0.70"))
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    total_s = sum(int(c["seconds"]) for c in CLIPS)
    print(f"model={model} size={size} clips={len(CLIPS)} seconds={total_s}")
    for c in CLIPS:
        print(f"\n[{c['name']}, {c['seconds']} s]\n{c['prompt']}")
    print(
        f"\nEstimated cost: {total_s} s x ${price:.2f}/s = ${estimate_usd(price):.2f}"
        " (one take each; budget 2-3 takes)"
    )
    if not args.yes:
        print("Dry run. Re-run with --yes after spend approval.")
        return 0

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY is not set in .env", file=sys.stderr)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        with httpx.Client(base_url=base_url, headers=headers, timeout=120) as client:
            preflight(client)
            for clip in CLIPS:
                generate(client, model, size, clip)
    except (VideoApiError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
