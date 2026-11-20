"""Marco's Slack-thread operations. Each subcommand prints one JSON object.

Run from the repo root:
  uv run python scripts/marco_ops.py clash --start 2026-12-01 --end 2026-12-03 --place "Austin"
  uv run python scripts/marco_ops.py replan-text --text "<slack message>" --thread-ts <ts>
  uv run python scripts/marco_ops.py cancel-propose --trip <trip_id> --text "<slack message>" --thread-ts <ts>
  uv run python scripts/marco_ops.py cancel-apply --approved-by <sender slack id>

Only Tokyo approves. Every apply step checks the sender id against SLACK_OWNER_ID.
Perk and Uber run in the browser after approval. These scripts return browser_todo lists.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
DATA = ROOT / "data"
MODEL = "anthropic/claude-sonnet-5-5"


class NotOwner(Exception):
    pass


def owner_id() -> str:
    if not os.environ.get("SLACK_OWNER_ID"):
        try:
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env")
        except ImportError:
            pass
    return os.environ.get("SLACK_OWNER_ID", "")


def require_owner(sender_id: str) -> None:
    """Only Tokyo's member id may approve. A display name never counts."""
    owner = owner_id()
    if not owner or not sender_id or sender_id.strip() != owner:
        raise NotOwner("only Tokyo can approve this action")


def overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return date.fromisoformat(a_start) <= date.fromisoformat(b_end) and \
        date.fromisoformat(b_start) <= date.fromisoformat(a_end)


def trips(include_cancelled: bool = False) -> list[dict]:
    out = []
    for f in sorted(DATA.glob("trip_*.json")):
        try:
            t = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if t.get("dates") and (include_cancelled or not t.get("cancelled")):
            out.append(t)
    return out


def same_place(a: str, b: str) -> bool:
    first = lambda s: (s or "").split(",")[0].strip().lower()
    return bool(first(a)) and first(a) == first(b)


def _summary(t: dict) -> dict:
    return {"trip_id": t["trip_id"], "place": t.get("place"), "traveller": t.get("traveller"),
            "dates": t["dates"], "perk_trip_id": t.get("perk_draft", {}).get("perk_trip_id")}


def find_clashes(start: str, end: str, existing: list[dict], place: str = "") -> list[dict]:
    """Overlapping trips to another place. A trip to the same place is the same trip, not a clash."""
    return [_summary(t) for t in existing
            if overlaps(start, end, t["dates"]["start"], t["dates"]["end"]) and not same_place(place, t.get("place", ""))]


def find_same_trip(start: str, end: str, existing: list[dict], place: str) -> dict | None:
    for t in existing:
        if same_place(place, t.get("place", "")) and overlaps(start, end, t["dates"]["start"], t["dates"]["end"]):
            return _summary(t)
    return None


def cli(module: str, *args: str) -> dict:
    p = subprocess.run(["uv", "run", "python", "-m", module, *args], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": "bad_output"}


def audit(trip, act, step, status, summary, sources, external_ref=None, approved_by=None):
    return {"trip_id": trip, "act": act, "step": step, "status": status, "summary": summary[:200],
            "sources": sources, "model": MODEL, "cost_usd": 0.0, "external_ref": external_ref,
            "supersedes": None, "approved_by": approved_by}


def record_many(rows: list[dict]) -> dict:
    return cli("services.audit", "record-many", "--json", json.dumps(rows))


def _d(s: str, days: int = 0) -> str:
    from datetime import timedelta
    return (date.fromisoformat(s) + timedelta(days=days)).isoformat()


def state_replan(t: dict, change: dict) -> dict:
    """Build the replan from the stored trip state, so it never depends on old audit rows."""
    old, new = change["old_dates"], change["new_dates"]
    shift = (date.fromisoformat(new["start"]) - date.fromisoformat(old["start"])).days
    out_day, home_day = _d(new["start"], -1), _d(new["end"], 1)
    perk = t.get("perk_draft", {}).get("perk_trip_id")
    ride = (t.get("ground") or [{}])[0]
    acts = []

    def add(step, cli_name, args, summary):
        acts.append({"n": len(acts) + 1, "step": step, "cli": cli_name, "args": args, "supersedes": None, "summary": summary})

    ids = t.get("calendar_event_ids") or []
    add("calendar", "services.gws calendar-move", {"event_ids": ids, "start": new["start"], "end": new["end"], "shift_days": shift},
        f"Move the {len(ids) or 5} calendar events by +{shift} days.")
    if t.get("task_id"):
        add("ticket", "services.gws ticket", {"task_id": t["task_id"], "due": _d(home_day, 3)},
            f"Move the expenses task due date to {_d(home_day, 3)}.")
    add("perk_fill", "browser perk", {"perk_trip": perk, "flight_out": out_day, "flight_home": home_day,
                                      "hotel_in": out_day, "hotel_out": home_day},
        f"Change Perk draft {perk}: workshop {new['start']} to {new['end']}, flights {out_day} and {home_day}, hotel {out_day} to {home_day}.")
    add("uber_cancel", "browser uber", {"ride": ride.get("reservation_id")},
        f"Cancel Uber ride {ride.get('reservation_id')} (free up to 1 h before).")
    add("uber_schedule", "browser uber", {"when_iso": f"{home_day}T05:30:00", "expense_code": ride.get("expense_code", "2K")},
        f"Reserve a new Uber to SFO on {home_day} 05:30, code {ride.get('expense_code', '2K')}.")
    for who, env, role in (("Ricardo", "APPROVER_EMAIL", "approver"), ("Bart", "CLIENT_EMAIL", "client contact")):
        add("email_draft", "services.gws draft-email",
            {"to": os.environ.get(env, f"{who.lower()}@example.invalid"),
             "subject": f"Novato workshop moved to {new['start']} to {new['end']}",
             "body": f"Hi {who},\n\nThe 2K AI workshop moved from {old['start']} to {new['start']}. "
                     f"I moved my travel to {out_day} to {home_day}.\n\nTokyo"},
            f"Draft a note to {who} ({role}). Draft only.")
    return {"proposal": f"Trip: {t['trip_id']}. The workshop moved from {old['start']} to {new['start']}. "
                        f"Marco proposes {len(acts)} actions. Nothing runs until Tokyo approves.",
            "actions": acts}


CHANGE_PATTERNS = [
    ("moved", r"\b(moved|postponed|rescheduled|pushed|shifted|delayed|brought forward)\b"),
    ("cancelled", r"\b(cancel+ed|called off|is off|won't happen|not happening)\b"),
    ("swap", r"\b(instead of|go instead|goes instead|will go instead|replace[sd]? \w+ on|in place of)\b"),
]
DATE_RE = (r"\b(\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|"
           r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}|\d{4}-\d{2}-\d{2}|"
           r"january|february|march|april|june|july|august|september|october|november|december|"
           r"mon(day)?|tue(sday)?|wed(nesday)?|thu(rsday)?|fri(day)?)\b")
TRIP_RE = r"\b(on-?site|trip|travel|fly|flight|visit|workshop|hackathon|offsite|conference|meetup|summit)\b"


def detect_change(text: str, places: list[str] | None = None) -> dict:
    """Cheap keyword gate for room messages. Returns the kind of trip change, or "none"."""
    import re

    t = (text or "").lower()
    known = [p.split(",")[0].strip().lower() for p in (places or []) if p]
    mentions_trip = bool(re.search(TRIP_RE, t)) or any(k and k in t for k in known)
    for kind, pat in CHANGE_PATTERNS:
        if re.search(pat, t) and mentions_trip:
            return {"change": kind}
    if mentions_trip and re.search(DATE_RE, t):
        return {"change": "new_trip"}
    return {"change": "none"}


# ---------- subcommands ----------
def cmd_clash(a) -> dict:
    existing = trips()
    hits = find_clashes(a.start, a.end, existing, a.place)
    same = find_same_trip(a.start, a.end, existing, a.place)
    if hits:
        record_many([audit(hits[0]["trip_id"], "other", "notify", "proposed",
                           f"New request {a.place} {a.start} to {a.end} overlaps trip {hits[0]['trip_id']}.",
                           [{"type": "slack", "ref": a.thread_ts or "", "quote": f"{a.place} {a.start} to {a.end}"}])])
    return {"request": {"place": a.place, "start": a.start, "end": a.end}, "clashes": hits,
            "existing_trip": same, "next": "plan with stored data" if same else ("flag clash" if hits else "plan new trip")}


def cmd_replan_text(a) -> dict:
    all_trips = trips(include_cancelled=True)
    if not all_trips:
        return {"error": "no_trip", "detail": "No stored trip to replan."}
    t = all_trips[0]
    ev = t.get("event_dates") or t["dates"]
    os.environ.setdefault("MARCO_TRIP_DATES", f"{ev['start']}:{ev['end']}")
    sys.path.insert(0, str(ROOT))
    from services.gws.__main__ import llm_extract

    ex = llm_extract("Slack thread message", a.text)
    if not ex:
        return {"error": "no_date_change", "detail": "I found no old and new date range in the message."}
    change = {"message_id": a.thread_ts or "", "subject": a.text[:120], **ex, "trip_id": t["trip_id"], "source": "slack"}
    plan = state_replan(t, change)
    (DATA / "replan_pending.json").write_text(json.dumps(
        {"thread_ts": a.thread_ts, "channel": a.channel, "change": change, "plan": plan}, indent=2))
    record_many([audit(t["trip_id"], "replan", "notify", "proposed",
                       f"Marco saw the date change in Slack and proposed {len(plan['actions'])} actions.",
                       [{"type": "slack", "ref": a.thread_ts or "", "quote": a.text[:200]}])])
    out = {"change": change, **plan}
    if a.post:
        import marco_card as mc
        facts = {**mc.from_plan(t["trip_id"], change, plan), "mention": owner_id(),
                 "lead": "The workshop moved. I can update your trip."}
        out["card"] = mc.post("replan", facts, a.channel or "C0CLLEH6D1N", a.thread_ts)
    return out


def new_traveller(text: str) -> str:
    """Name in 'X will go instead', or ''."""
    import re

    m = re.search(r"\b([A-Z][a-z]+)\b(?= (will )?(go|goes|travel|travels)\b.*\binstead)", text or "")
    return m.group(1) if m else ""


def cmd_cancel_propose(a) -> dict:
    all_trips = trips(include_cancelled=True)
    if not all_trips:
        return {"error": "no_trip", "detail": "No stored trip to cancel."}
    t = next((x for x in all_trips if x["trip_id"] == a.trip), None) or all_trips[0]
    perk = t.get("perk_draft", {}).get("perk_trip_id")
    actions = [
        {"step": "perk_cancel", "summary": f"Delete Perk draft {perk} for {t.get('traveller')}."},
        {"step": "uber_cancel", "summary": "Cancel the reserved Uber ride (free up to 60 min before)."},
        {"step": "calendar", "summary": "Remove the trip blocks from the calendar."},
    ]
    rows = [audit(t["trip_id"], "other", s["step"], "proposed", s["summary"],
                  [{"type": "slack", "ref": a.thread_ts or "", "quote": a.text[:200]}],
                  external_ref=perk if s["step"] == "perk_cancel" else None) for s in actions]
    record_many(rows)
    (DATA / "cancel_pending.json").write_text(json.dumps(
        {"trip_id": t["trip_id"], "thread_ts": a.thread_ts, "text": a.text, "actions": actions}, indent=2))
    out = {"trip_id": t["trip_id"], "traveller": t.get("traveller"), "actions": actions}
    if a.post:
        import marco_card as mc
        kinds = {"perk_cancel": "perk", "uber_cancel": "uber", "calendar": "calendar"}
        facts = {"traveller": t.get("traveller"), "mention": owner_id(),
                 "lead": f"{new_traveller(a.text) or 'Someone else'} goes instead. I can cancel your bookings.",
                 "actions": [{"kind": kinds.get(x["step"], ""), "text": x["summary"]} for x in actions],
                 "free_cancel": ["Perk draft: nothing booked", "Uber: free up to 1 h before"]}
        out["card"] = mc.post("cancel", facts, a.channel or "C0CLLEH6D1N", a.thread_ts)
    return out


def cmd_cancel_apply(a) -> dict:
    require_owner(a.approved_by)
    pending = json.loads((DATA / "cancel_pending.json").read_text())
    trip = pending["trip_id"]
    src = [{"type": "slack", "ref": pending.get("thread_ts") or "", "quote": "approve"}]
    rows = [audit(trip, "other", "approval", "approved", "Tokyo approved the cancellation.", src,
                  approved_by=a.approved_by)]
    res = record_many(rows)
    f = DATA / f"trip_{trip.split('-')[0]}.json"
    if f.exists():
        st = json.loads(f.read_text())
        st["cancelled"] = True
        f.write_text(json.dumps(st, indent=2))
    out_card = None
    if a.post:
        import marco_card as mc
        kinds = {"perk_cancel": "perk", "uber_cancel": "uber", "calendar": "calendar"}
        who = new_traveller(pending.get("text", "")) or "The new traveller"
        facts = {"traveller": "Tokyo", "mention": a.approved_by,
                 "items": [{"kind": kinds.get(x["step"], ""), "text": x["summary"], "ref": x.get("ref")} for x in pending["actions"]],
                 "next": f"{who} needs a booking. Tag @Marco with the dates to plan it."}
        out_card = mc.post("cancelled", facts, a.channel or "C0CLLEH6D1N", pending.get("thread_ts"))
    return {"trip_id": trip, "status": "approved", "audit_ids": res.get("ids", []), "card": out_card,
            "browser_todo": pending["actions"],
            "note": "Run each action in the browser (Perk: Chrome, delete draft. Uber: Chrome 4, cancel). Audit each as cancelled with its external_ref."}


GATE_TTL_S = 60


def gate_on(name: str = "proactive_mode", now: float | None = None) -> bool:
    """Statsig gate, cached in data/ for one minute so room checks stay fast."""
    import time

    now = now or time.time()
    cache = DATA / "gate_cache.json"
    try:
        c = json.loads(cache.read_text())
        if c.get("name") == name and now - c.get("at", 0) < GATE_TTL_S:
            return bool(c["enabled"])
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    enabled = bool(cli("services.audit", "gate", "--name", name).get("enabled", False))
    try:
        cache.write_text(json.dumps({"name": name, "enabled": enabled, "at": now}))
    except OSError:
        pass
    return enabled


def room_check(text: str, places: list[str], gate=gate_on) -> dict:
    """Decide if an untagged room message needs Marco. Gate first, then the keyword classifier."""
    if not gate("proactive_mode"):
        return {"act": False, "gate": "proactive_mode=off", "change": "skipped"}
    change = detect_change(text, places)["change"]
    return {"act": change != "none", "gate": "proactive_mode=on", "change": change}


def cmd_room_check(a) -> dict:
    return room_check(a.text, [t.get("place", "") for t in trips(include_cancelled=True)])


def cmd_detect_change(a) -> dict:
    return detect_change(a.text, [t.get("place", "") for t in trips(include_cancelled=True)])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="marco_ops")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect-change").add_argument("--text", required=True)
    sub.add_parser("room-check").add_argument("--text", required=True)
    s = sub.add_parser("clash")
    s.add_argument("--start", required=True)
    s.add_argument("--end", required=True)
    s.add_argument("--place", default="")
    s.add_argument("--thread-ts")
    s = sub.add_parser("replan-text")
    s.add_argument("--text", required=True)
    s.add_argument("--channel", default="")
    s.add_argument("--post", action="store_true", help="post the replan card in the thread")
    s.add_argument("--thread-ts")
    s = sub.add_parser("cancel-propose")
    s.add_argument("--trip", default="")
    s.add_argument("--channel", default="")
    s.add_argument("--post", action="store_true")
    s.add_argument("--text", required=True)
    s.add_argument("--thread-ts")
    s = sub.add_parser("cancel-apply")
    s.add_argument("--approved-by", required=True)
    s.add_argument("--channel", default="")
    s.add_argument("--post", action="store_true", help="post the cancelled card (run after the browser steps)")
    a = ap.parse_args(argv)
    fn = {"room-check": cmd_room_check, "detect-change": cmd_detect_change, "clash": cmd_clash, "replan-text": cmd_replan_text,
          "cancel-propose": cmd_cancel_propose, "cancel-apply": cmd_cancel_apply}[a.cmd]
    try:
        print(json.dumps(fn(a)))
        return 0
    except NotOwner as e:
        print(json.dumps({"error": "not_owner", "detail": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
