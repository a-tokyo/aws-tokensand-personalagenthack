"""Act 2 watcher: poll Gmail every 60 s, and post a replan proposal to #marco-agent as Marco.

Usage (repo root, background):
  nohup uv run python scripts/marco_watch.py > data/logs/watch.log 2>&1 &
  uv run python scripts/marco_watch.py --once   # one poll, for a test

It only reads Gmail and posts one Slack message per change. It runs no action.
Tokyo's "approve" reply in that thread reaches Marco, who applies the stored proposal.
Secrets come from the repo .env. Nothing secret is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATE = DATA / "watch_state.json"
CHANNEL = os.environ.get("MARCO_CHANNEL", "C0CKA55HJ31")
TRIP = os.environ.get("MARCO_DEFAULT_TRIP", "novato-2k-workshop-2026-11")
# The trip's current workshop dates. A mail that names only the new dates replans from these.
TRIP_DATES = os.environ.get("MARCO_TRIP_DATES", "2026-11-30:2026-12-02")


def log(msg: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {msg}", flush=True)


def cli(module: str, *args: str) -> dict:
    env = {**os.environ, "MARCO_DEFAULT_TRIP": TRIP, "MARCO_TRIP_DATES": TRIP_DATES}
    p = subprocess.run(["uv", "run", "python", "-m", module, *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=180)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": "bad_output", "detail": (p.stderr or p.stdout)[-300:]}


def render(change: dict, plan: dict, owner: str) -> str:
    old, new = change["old_dates"], change["new_dates"]
    lines = [f"<@{owner}> Trip change: {change.get('subject', '')[:80]}",
             f"Trip: {change['trip_id']}. Old dates: {old['start']} to {old['end']}. New dates: {new['start']} to {new['end']}.",
             "Actions:"]
    lines += [f"• {a['n']}) {a['summary']}" for a in plan["actions"]]
    lines += ["On approve: Perk and Uber change in the browser. Emails stay drafts.", 'Reply "@Marco approve" to apply.']
    return "\n".join(lines)


def post(text: str) -> str | None:
    r = httpx.post("https://slack.com/api/chat.postMessage", timeout=30,
                   headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
                   json={"channel": CHANNEL, "text": text, "unfurl_links": False})
    body = r.json()
    if not body.get("ok"):
        log(f"slack post failed: {body.get('error')}")
        return None
    return body["ts"]


def poll_once(since: str) -> None:
    res = cli("services.gws", "watch-gmail", "--since", since)
    if "error" in res:
        log(f"watch-gmail error: {res.get('error')}")
        return
    for change in res.get("changes", []):
        change["trip_id"] = TRIP
        plan = cli("services.gws", "replan", "--trip", TRIP, "--json", json.dumps(change))
        if "error" in plan:
            log(f"replan error: {plan.get('error')}")
            continue
        ts = post(render(change, plan, os.environ.get("SLACK_OWNER_ID", "")))
        pending = {"thread_ts": ts, "channel": CHANNEL, "change": change, "plan": plan}
        (DATA / "replan_pending.json").write_text(json.dumps(pending, indent=2))
        cli("services.audit", "record", "--json", json.dumps({
            "trip_id": TRIP, "act": "replan", "step": "notify", "status": "proposed",
            "summary": f"Marco saw '{change.get('subject', '')[:80]}' and proposed {len(plan['actions'])} actions.",
            "sources": [{"type": "gmail", "ref": change.get("message_id", ""), "quote": change.get("subject", "")[:200]}],
            "model": None, "cost_usd": 0.0, "external_ref": ts, "supersedes": None, "approved_by": None}))
        log(f"posted replan for {TRIP} ({len(plan['actions'])} actions)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--since")
    a = ap.parse_args(argv)
    load_dotenv(ROOT / ".env")
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    since = a.since or state.get("since") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    while True:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            poll_once(since)
        except Exception as exc:  # keep the loop alive for the demo
            log(f"poll failed: {type(exc).__name__}")
        # Overlap the window by 5 minutes. watch-gmail dedupes message ids.
        since_dt = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() - 300
        since = datetime.fromtimestamp(since_dt, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        STATE.write_text(json.dumps({"since": since}))
        if a.once:
            return 0
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
