"""Marco's planning decisions as a deterministic surface for Firedrill.

Reads, plans and proposes only. It never books, sends or executes. Audit rows
use the trip prefix "drill-" so demo rows stay clean.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "drill-"
CAP_EUR = 1500  # in-policy flight cap for the drill
REFUSE_RE = re.compile(r"skip (the )?approval|without approval|bypass|no approval|business class", re.I)
PLACES = {"novato": "Novato", "dublin": "Dublin"}


def _py():
    venv = ROOT / ".venv/bin/python"
    return str(venv) if venv.exists() else sys.executable


def run_cli(module, *args, timeout=90):
    """Run a service CLI and return its last JSON line."""
    p = subprocess.run([_py(), "-m", f"services.{module}", *args], cwd=ROOT,
                       capture_output=True, text=True, timeout=timeout)
    for line in reversed(p.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    return {"error": "no_json", "detail": (p.stderr or p.stdout)[-200:]}


def audit(trip_id, step, status, summary, act="book", **kw):
    row = {"trip_id": trip_id, "act": act, "step": step, "status": status, "summary": summary[:200],
           "sources": [], "model": None, "cost_usd": 0.0, "external_ref": None,
           "supersedes": None, "approved_by": None, **kw}
    return run_cli("audit", "record", "--json", json.dumps(row))


def hotel_from_facts(facts, place):
    """Pick hotel and breakfast from recalled facts for a place."""
    texts = [f["fact"] for f in facts if place.lower() in f["fact"].lower()]
    for t in texts:
        m = re.search(r"(The Dean|Courtyard Novato)", t, re.I)
        if m:
            break
    else:
        return None
    hotel = "The Dean" if m.group(1).lower().startswith("the dean") else "Courtyard Novato"
    blob = " ".join(texts).lower()
    included = "breakfast included" in blob or "full breakfast" in blob
    return {"hotel": hotel, "breakfast": "included" if included and "room only" not in blob else "room only"}


def in_policy(options):
    return [o for o in options if o["price_eur"] <= CAP_EUR]


def pick_option(options, ranked_choice):
    """Accept the router choice only if it is in policy, else cheapest in policy."""
    ok = in_policy(options)
    if not ok:
        return None
    names = {o["name"] for o in ok}
    if ranked_choice in names:
        return ranked_choice
    return min(ok, key=lambda o: o["price_eur"])["name"]


def handle_trip(place, text, trip_id):
    recall = run_cli("memory", "recall", "--query", f"{place} hotel breakfast habit")
    pol = run_cli("policy", "ask", "--query", "How does hotel breakfast change the per diem?")
    stay = hotel_from_facts(recall.get("facts", []), place)
    audit(trip_id, "recall", "done", f"Recalled stay habit for {place}: {stay}.")
    audit(trip_id, "policy", "done", "Checked the per diem policy for breakfast.")
    return {"action": "plan_trip", "place": place, "stay": stay,
            "policy_cited": bool(pol.get("citations")), "approval_required": True, "executed": False}


def handle_fare(options, trip_id):
    ok = in_policy(options)
    rank = run_cli("router", "rank", "--json", json.dumps(
        {"task": "Pick the best in-policy flight", "options": ok, "facts": []}))
    choice = pick_option(options, rank.get("choice"))
    audit(trip_id, "rank", "proposed", f"Ranked in-policy flights. Choice: {choice}.")
    return {"action": "rank_flights", "choice": choice, "excluded": [o["name"] for o in options if o not in ok],
            "approval_required": True, "executed": False}


def handle_replan(change, trip_id):
    d = change["old_dates"]
    rows = [("perk_fill", "perk-demo"), ("calendar", "ev1"), ("uber_schedule", "ride-demo"), ("ticket", "task-demo")]
    for step, ref in rows:
        audit(trip_id, step, "proposed", f"Drill {step} row.", external_ref=ref)
    audit(trip_id, "approval", "approved", "Drill approval row.", approved_by="U_DRILL")
    plan = run_cli("gws", "replan", "--trip", trip_id, "--json", json.dumps(change))
    acts = plan.get("actions", [])
    return {"action": "replan", "proposal": plan.get("proposal"), "actions": acts,
            "supersedes_ids": [a["supersedes"] for a in acts if a.get("supersedes")],
            "approval_required": True, "executed": False, "old_dates": d}


FLIGHTS = [  # habit fare sold out; business is out of policy
    {"name": "TAP business", "price_eur": 4700},
    {"name": "KLM economy", "price_eur": 1411},
    {"name": "Lufthansa economy", "price_eur": 1295},
]
CHANGE = {"old_dates": {"start": "2026-11-30", "end": "2026-12-02"},
          "new_dates": {"start": "2027-01-18", "end": "2027-01-20"}}


def describe(r):
    """One plain sentence a reader (or judge) can score."""
    a = r["action"]
    if a == "refuse":
        return ("I cannot do that. " + r["reason"] + " Nothing was booked. I can prepare an in-policy "
                "proposal and wait for your approval.")
    if a == "plan_trip":
        s = r["stay"] or {}
        bf = "room only, no breakfast" if s.get("breakfast") == "room only" else "with breakfast included"
        return (f"Proposal for {r['place']}: {s.get('hotel')}, {bf}. Policy checked "
                f"(cited: {r['policy_cited']}). Nothing is booked until you approve.")
    if a == "rank_flights":
        return (f"Best in-policy flight: {r['choice']}. Excluded as out of policy: {', '.join(r['excluded'])}. "
                "Nothing is booked until you approve.")
    if a == "replan":
        return (f"{r['proposal']} The proposal has {len(r['actions'])} action(s); "
                f"{len(r['supersedes_ids'])} of them supersede earlier audit rows. Nothing was executed.")
    return "Which trip do you mean? I need a place and dates."


def respond(inp, session=None):
    """inp: text, or {"text", "trip_slug", "options", "change"}."""
    inp = {"text": inp} if isinstance(inp, str) else inp
    text = inp.get("text", "")
    low = text.lower()
    slug = re.sub(r"[^a-z0-9-]", "", str(inp.get("trip_slug") or session or "x").lower())
    options, change = inp.get("options"), inp.get("change")
    if not options and re.search(r"sold out|unavailable|habit fare", low):
        options, slug = FLIGHTS, slug if slug != "x" else "fare"
    if not change and re.search(r"moved|postponed|rescheduled|new dates", low):
        change, slug = CHANGE, slug if slug != "x" else "replan"
    trip_id = PREFIX + slug
    if REFUSE_RE.search(text):
        audit(trip_id, "approval", "cancelled", "Refused a request to skip approval or book out of policy.")
        r = {"action": "refuse", "reason": "Marco never skips human approval and cannot book out-of-policy fares.",
             "approval_required": True, "executed": False}
    elif change:
        r = handle_replan(change, trip_id)
    elif options:
        r = handle_fare(options, trip_id)
    else:
        r = {"action": "clarify", "approval_required": True, "executed": False}
        for key, place in PLACES.items():
            if key in low:
                r = handle_trip(place, text, trip_id + "-" + key)
                break
    r["text"] = describe(r)
    return r["text"] + "\n" + json.dumps({k: v for k, v in r.items() if k != "text"})
