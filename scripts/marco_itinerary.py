"""Post the trip itinerary as a Slack Block Kit message in a thread, as Marco.

Run from the repo root:
  uv run python scripts/marco_itinerary.py --thread-ts <ts> --mention <slack id> [--status "<one STE line>"] [--update-ts <ts>]

Reads data/trip_novato.json and the audit row count. Prints {"ts": ...}.
With --update-ts it edits that message instead of posting a new one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNEL = os.environ.get("MARCO_CHANNEL", "C0CKA55HJ31")


PERK_URL = "https://app.perk.com/trips"


def _day(d: date | datetime) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _ask(state: dict) -> str:
    if state.get("cancelled"):
        return "❌ *Cancelled.* Perk draft and Uber ride are cancelled."
    st = state["perk_draft"].get("status", "").lower()
    if "approved" in st or ("submitted" in st and "not submitted" not in st):
        return "✅ *Approved.* Sent to Perk. Calendar and expenses task are set."
    return "*Ready for you.* Reply `@Marco approve submit` to send to Perk."


def _flight_field(f: dict) -> dict:
    dep, arr = _dt(f["depart"]), _dt(f["arrive"])
    plus = f" +{(arr.date() - dep.date()).days}" if arr.date() > dep.date() else ""
    return {"type": "mrkdwn", "text": (
        f"*{f['leg']}* · {_day(dep)}\n*{dep:%H:%M} {f['from']} → {arr:%H:%M} {f['to']}{plus}*\n"
        f"{f['flight_no']} · via {f['via']}\n{f['airline']} · {f['cabin']}")}


def _hotel_cancel(state: dict) -> str:
    h = state["hotel_info"]
    if h.get("free_cancel"):
        return h["free_cancel"]
    m = re.search(r"cancellation before (\d{1,2} \w{3} \d{4})(?: (\d\d:\d\d))?", state["perk_draft"].get("hotel", ""))
    if not m:
        return ""
    return f"{_day(datetime.strptime(m.group(1), '%d %b %Y'))} {m.group(2) or ''}".strip()


def _checklist(state: dict) -> list[str]:
    items = []
    if state.get("flights"):
        out = _dt(state["flights"][0]["depart"])
        items.append(f"Check in online from {_day(out - timedelta(days=1))} {out:%H:%M} (24 h before).")
    if cancel := _hotel_cancel(state):
        items.append(f"Hotel free cancel until {cancel}.")
    due = date.fromisoformat(state["dates"]["end"]) + timedelta(days=3)
    items.append(f"File expenses by {_day(due)} (task set).")
    items.append("Register the trip in Mindera People.")
    return items


VERIFIED = {"completed", "approved"}


def _persona_button(state: dict) -> list[dict]:
    """Link button to the Persona check while the approver is not verified yet."""
    pv = state.get("persona") or {}
    if not pv.get("url") or pv.get("status") in VERIFIED:
        return []
    return [{"type": "button", "action_id": "persona_verify", "style": "primary",
             "text": {"type": "plain_text", "emoji": True, "text": "🪪 Verify it's you (Persona)"}, "url": pv["url"]}]


def build_blocks(state: dict, mention: str, audit_count: int, status: str = "") -> list[dict]:
    h, ride, draft = state["hotel_info"], state["ground"][0], state["perk_draft"]
    place = state["place"].split(",")[0]
    start, end = date.fromisoformat(state["dates"]["start"]), date.fromisoformat(state["dates"]["end"])
    meta = [f"Trip for <@{mention}>", f"Perk {'draft' if not state.get('cancelled') else 'cancelled'}"]
    if draft.get("in_policy", True):
        meta.append("In policy ✅")
    if draft.get("checkout_total_eur") is not None:
        meta.append(f"EUR {draft['checkout_total_eur']:,.0f}")
    ask = f"<@{mention}> {status}" if status else _ask(state)
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "emoji": True, "text": f"✈️ {place} · {_day(start)} – {_day(end)}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(meta)}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": ask}},
        {"type": "divider"},
    ]
    if h.get("image_url"):
        blocks.append({"type": "image", "image_url": h["image_url"], "alt_text": f"{h['name']}, {place}"})
    if state.get("flights"):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "✈️ *Flights*"},
                       "fields": [_flight_field(f) for f in state["flights"][:10]]})
        blocks.append({"type": "divider"})
    rate = re.search(r"EUR ([\d,.]+)", draft.get("hotel", ""))
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "🏨 *Hotel*"}, "fields": [
        {"type": "mrkdwn", "text": f"*{h['name']}*\n{h['address']}"},
        {"type": "mrkdwn", "text": f"*Check-in* {_day(start)} {h['check_in']}\n*Check-out* {_day(end)} {h['check_out']}"},
        {"type": "mrkdwn", "text": f"*Room*\n{h['room']}" + (f" · EUR {rate.group(1)}" if rate else "")},
        {"type": "mrkdwn", "text": f"*Breakfast*\n{h['breakfast']}"},
    ]})
    blocks.append({"type": "divider"})
    to = state["flights"][-1]["from"] if state.get("flights") else ride.get("dropoff", "airport").split(",")[0]
    when = ride["when"].replace(f" {end.year}", "")
    fare = f" · USD {ride['fare_usd']:.2f}" if ride.get("fare_usd") else ""
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🚕 *Ride to {to}*"}, "fields": [
        {"type": "mrkdwn", "text": f"*When*\n{when}"},
        {"type": "mrkdwn", "text": f"*Route*\n{ride['pickup'].split(',')[0]} → {to}"},
        {"type": "mrkdwn", "text": f"*Profile*\n{ride['product']} · Mindera · code {ride['expense_code']}{fare}"},
        {"type": "mrkdwn", "text": f"*Free cancel*\n{ride['cancel'][0].upper()}{ride['cancel'][1:]}"},
    ]})
    blocks.append({"type": "divider"})
    if not state.get("cancelled"):
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "📋 *Checklist*\n" + "\n".join(f"• {i}" for i in _checklist(state))}})
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "action_id": "open_perk", "text": {"type": "plain_text", "text": "Open in Perk"},
             "url": draft.get("itinerary_url") or PERK_URL}] + _persona_button(state)})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": (
        f"Audit trail: {audit_count} steps · trip `{state['trip_id']}` · sources: Cognee memory, Senso policy")}]})
    return blocks


def audit_count(trip_id: str) -> int:
    p = subprocess.run(["uv", "run", "python", "-m", "services.audit", "list", "--trip", trip_id], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    try:
        return len(json.loads(p.stdout.strip().splitlines()[-1])["rows"])
    except (IndexError, json.JSONDecodeError, KeyError):
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default=CHANNEL, help="Slack channel id of the thread")
    ap.add_argument("--thread-ts", required=True)
    ap.add_argument("--mention", required=True)
    ap.add_argument("--status", default="")
    ap.add_argument("--update-ts")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    import httpx

    load_dotenv(ROOT / ".env")
    state = json.loads((ROOT / "data" / "trip_novato.json").read_text())
    blocks = build_blocks(state, a.mention, audit_count(state["trip_id"]), a.status)
    text = f"{state['place']} trip itinerary"
    if a.dry_run:
        print(json.dumps({"blocks": blocks}))
        return 0
    body = {"channel": a.channel, "text": text, "blocks": blocks}
    method = "chat.update" if a.update_ts else "chat.postMessage"
    body.update({"ts": a.update_ts} if a.update_ts else {"thread_ts": a.thread_ts, "unfurl_links": False})
    r = httpx.post(f"https://slack.com/api/{method}", json=body, timeout=30,
                   headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}).json()
    if not r.get("ok"):
        print(json.dumps({"error": r.get("error")}))
        return 1
    print(json.dumps({"ts": r["ts"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
