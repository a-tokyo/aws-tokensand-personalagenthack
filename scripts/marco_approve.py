"""Apply Tokyo's "approve <option>" for a planned trip, in one deterministic run.

Usage (repo root):
  uv run python scripts/marco_approve.py --trip <trip_id> --option A --approved-by <slack member id>

What it does, in order, each step with an audit row:
  1. approval row (approved_by = Tokyo).
  2. calendar-block for the trip span (real write, "[Marco test]" prefix).
  3. expenses ticket (Google Tasks) due 3 days after the trip.
  4. prints browser_todo: Perk option apply (and submit only with --submit), Uber time move.
     Marco runs those in the browser next and audits each with its external_ref.
It prints one JSON object for Marco to summarise in the thread.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "anthropic/claude-sonnet-5-5"


def cli(module: str, *args: str) -> dict:
    p = subprocess.run(["uv", "run", "python", "-m", module, *args], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": "bad_output", "detail": (p.stderr or p.stdout)[-300:]}


def row(trip, step, status, summary, sources, external_ref=None, supersedes=None, approved_by=None):
    return {"trip_id": trip, "act": "book", "step": step, "status": status, "summary": summary[:200],
            "sources": sources, "model": MODEL, "cost_usd": 0.0, "external_ref": external_ref,
            "supersedes": supersedes, "approved_by": approved_by}


def calendar_events(state: dict) -> list[dict]:
    """Per-item calendar events built from the stored trip state."""
    h, ride, perk = state["hotel_info"], state["ground"][0], state["perk_draft"]["perk_trip_id"]
    ev = state["event_dates"]
    out = []
    for f in state["flights"]:
        out.append({"title": f"Flight {f['from']}-{f['to']} {f['flight_no']}", "start": f["depart"], "start_tz": f["depart_tz"],
                    "end": f["arrive"], "end_tz": f["arrive_tz"], "location": f"{f['from']} airport",
                    "description": f"{f['airline']} {f['flight_no']} via {f['via']}. {f['cabin']}. Check in online 24 h before. Perk trip {perk}."})
    out.append({"title": f"Hotel: {h['name']}", "start": state["dates"]["start"],
                "end": (date.fromisoformat(state["dates"]["end"]) - timedelta(days=1)).isoformat(), "location": h["address"],
                "description": f"Check-in {h['check_in']}, check-out {h['check_out']}. {h['room']}. {h['breakfast']} Perk trip {perk}."})
    out.append({"title": "2K AI workshop (Bart), Novato", "start": ev["start"], "end": ev["end"], "location": "2K, Novato, CA",
                "description": "On-site workshop with 2K."})
    when = ride["when"].split()  # "Fri 4 Dec 2026 05:30 PST"
    t = when[4]
    end_t = f"{int(t[:2]) + 1:02d}{t[2:]}"
    out.append({"title": "Uber to SFO", "start": f"{state['dates']['end']}T{t}", "end": f"{state['dates']['end']}T{end_t}",
                "start_tz": "America/Los_Angeles", "location": ride["pickup"],
                "description": f"UberX, Mindera profile, expense code {ride['expense_code']}. Reservation {ride['reservation_id']}. {ride['cancel']}."})
    return out


def items_exist(prev: dict) -> bool:
    """Check with Google that every event and the task from an earlier run still exist."""
    ids = prev.get("calendar", {}).get("event_ids", [])
    task = prev.get("ticket", {}).get("task_id")
    if not ids or not task:
        return False
    checks = [cli("services.gws", "exists", "--event-id", i) for i in ids]
    checks.append(cli("services.gws", "exists", "--task-id", task))
    return all(c.get("exists") for c in checks)


def latest(rows, step):
    hits = [r for r in rows if r.get("step") == step]
    return hits[-1] if hits else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trip", required=True)
    ap.add_argument("--option", required=True)
    ap.add_argument("--approved-by", required=True)
    ap.add_argument("--submit", action="store_true", help="only when the approve message says 'submit'")
    ap.add_argument("--thread-ts", help="Slack thread ts of the approve message; makes the run idempotent")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT / "scripts"))
    from marco_ops import NotOwner, require_owner

    try:
        require_owner(a.approved_by)
    except NotOwner as e:
        print(json.dumps({"error": "not_owner", "detail": str(e)}))
        return 1

    marker = ROOT / "data" / "approve_done" / f"{a.thread_ts or 'none'}_{a.option}.json"
    if marker.exists():  # idempotent per (thread, option), but only if the items still exist
        prev = json.loads(marker.read_text())
        if items_exist(prev):
            print(json.dumps({**prev, "already_done": True}))
            return 0
        marker.unlink()

    state = json.loads((ROOT / "data" / "trip_novato.json").read_text())
    draft = state["perk_draft"]
    perk_id = draft["perk_trip_id"]
    start, end = "2026-11-30", "2026-12-04"
    slack_src = [{"type": "slack", "ref": a.thread_ts or "slack", "quote": f"approve {a.option}"}]
    perk_src = [{"type": "perk", "ref": draft["itinerary_url"], "quote": "Saved in drafts"}]
    rows = cli("services.audit", "list", "--trip", a.trip).get("rows", [])
    out: dict = {"trip_id": a.trip, "option": a.option}

    # 1. approval
    prop = latest(rows, "perk_fill") or latest(rows, "notify")
    ap_row = cli("services.audit", "record", "--json", json.dumps(row(
        a.trip, "approval", "approved", f"Tokyo approved option {a.option} for the Novato trip.",
        slack_src, external_ref=perk_id, supersedes=prop and prop["id"], approved_by=a.approved_by)))
    out["approval_row"] = ap_row.get("id")

    # 2. calendar: one event per item (real writes)
    ids = []
    for ev in calendar_events(state):
        cal = cli("services.gws", "calendar-event", "--json", json.dumps(ev))
        ids += cal.get("event_ids", [])
    ok = len(ids) == len(calendar_events(state))
    cli("services.audit", "record", "--json", json.dumps(row(
        a.trip, "calendar", "done" if ok else "failed",
        f"Marco added {len(ids)} calendar events: flights, hotel, workshop, Uber." if ok else f"Calendar: {len(ids)} events added, some failed.",
        [{"type": "calendar", "ref": "primary", "quote": "[Marco] Flight OPO-SFO KL1570 + KL605"}],
        external_ref=",".join(ids) or None, approved_by=a.approved_by)))
    out["calendar"] = {"event_ids": ids}

    # 3. expenses ticket (Google Tasks)
    due = (date.fromisoformat(end) + timedelta(days=3)).isoformat()
    tk = cli("services.gws", "ticket", "--backend", "gtasks", "--json", json.dumps(
        {"title": "Submit Novato trip expenses (2K)", "due": due,
         "description": f"Perk draft {perk_id}. Uber code 2K. Receipts: breakfast, Uber."}))
    ok = "task_id" in tk
    cli("services.audit", "record", "--json", json.dumps(row(
        a.trip, "ticket", "done" if ok else "failed",
        f"Marco created the expenses task, due {due}." if ok else "Expenses task failed.",
        [{"type": "calendar", "ref": "gtasks:@default", "quote": "Submit Novato trip expenses (2K)"}],
        external_ref=tk.get("task_id"), approved_by=a.approved_by)))
    out["ticket"] = tk

    # 4-5. Perk and Uber run in the browser. Marco does them next, per the skills, and audits each.
    ride = state["ground"][0]
    out["browser_todo"] = [
        {"step": "perk_fill", "browser": "Chrome", "do": f"Apply option {a.option} to Perk draft {perk_id} (skill perk-booker step 10b). Extend the hotel if proposed."},
        {"step": "uber_schedule", "browser": "Chrome 4", "do": f"Move ride {ride.get('reservation_id')} to the proposed time. Edit allows 7 days ahead only, so cancel and reserve again (skill uber-schedule). Mindera profile, code 2K."},
    ]
    if a.submit:
        out["browser_todo"].append({"step": "perk_submit", "browser": "Chrome", "do": f"Press 'Send approval request' for Perk trip {perk_id} (skill perk-booker step 8)."})
    # Keep the live ids with the trip, so a replan finds them without old audit rows.
    state["calendar_event_ids"] = out["calendar"]["event_ids"]
    state["task_id"] = out.get("ticket", {}).get("task_id")
    (ROOT / "data" / "trip_novato.json").write_text(json.dumps(state, indent=2))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(out))
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
