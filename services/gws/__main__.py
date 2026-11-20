"""gws actions: calendar, drafts, tickets, Gmail watcher, replan. See docs/contracts.md."""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PROCESSED = DATA / "gws_processed_ids.json"
TITLE_PREFIX = "[Marco] "
SELF_EMAIL = os.environ.get("MARCO_SELF_EMAIL", "ahmed.tokyo@mindera.com")
DEFAULT_TRIP = os.environ.get("MARCO_DEFAULT_TRIP", "novato-2026-11-30")


class GwsError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass


# ---------- gws wrapper ----------
def _gws_bin():
    return shutil.which("gws") or str(Path.home() / ".local/bin/gws")


def gws(args):
    """Run gws and return parsed JSON. Never prints secrets."""
    cmd = [_gws_bin(), *args]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise GwsError("gws_failed", (p.stderr or p.stdout)[-400:])
    out = "\n".join(l for l in p.stdout.splitlines() if not l.startswith("Using keyring"))
    try:
        return json.loads(out) if out.strip() else {}
    except json.JSONDecodeError:
        raise GwsError("gws_bad_output", out[:200])


# ---------- date helpers ----------
def _day(s):
    return date.fromisoformat(s[:10])


def _event_times(start, end):
    """All-day span. Google end date is exclusive, so add one day."""
    return {"start": {"date": start[:10]},
            "end": {"date": (_day(end) + timedelta(days=1)).isoformat()}}


def _prefixed(title):
    return title if title.startswith(TITLE_PREFIX) else TITLE_PREFIX + title


# ---------- calendar ----------
def calendar_block(p):
    body = {"summary": _prefixed(p.get("title") or p.get("trip_id", "Trip")),
            "description": f"Marco trip {p.get('trip_id', '')}. Test block.",
            **_event_times(p["start"], p["end"])}
    r = gws(["calendar", "events", "insert", "--params", json.dumps({"calendarId": "primary", "sendUpdates": "none"}),
             "--json", json.dumps(body)])
    return {"event_ids": [r["id"]]}


def _when(v, tz):
    return {"date": v} if len(v) == 10 else {"dateTime": v if len(v) > 16 else v + ":00", "timeZone": tz}


def calendar_event(p):
    """One timed or all-day event. start/end: YYYY-MM-DD (all-day, end inclusive) or YYYY-MM-DDTHH:MM."""
    if len(p["start"]) == 10:
        times = _event_times(p["start"], p["end"])
    else:
        times = {"start": _when(p["start"], p.get("start_tz", "America/Los_Angeles")),
                 "end": _when(p["end"], p.get("end_tz", p.get("start_tz", "America/Los_Angeles")))}
    body = {"summary": _prefixed(p["title"]), "description": p.get("description", ""),
            "location": p.get("location", ""), **times}
    r = gws(["calendar", "events", "insert", "--params", json.dumps({"calendarId": "primary", "sendUpdates": "none"}),
             "--json", json.dumps(body)])
    return {"event_ids": [r["id"]]}


def _shift(t, days):
    if "date" in t:
        return {"date": (_day(t["date"]) + timedelta(days=days)).isoformat()}
    dt = datetime.fromisoformat(t["dateTime"]) + timedelta(days=days)
    return {"dateTime": dt.isoformat(), **({"timeZone": t["timeZone"]} if t.get("timeZone") else {})}


def calendar_move(p):
    if p.get("shift_days"):  # per-item events: keep each time, shift the day
        for eid in p["event_ids"]:
            ev = gws(["calendar", "events", "get", "--params", json.dumps({"calendarId": "primary", "eventId": eid})])
            gws(["calendar", "events", "patch",
                 "--params", json.dumps({"calendarId": "primary", "eventId": eid, "sendUpdates": "none"}),
                 "--json", json.dumps({"start": _shift(ev["start"], p["shift_days"]), "end": _shift(ev["end"], p["shift_days"])})])
        return {"event_ids": p["event_ids"], "shift_days": p["shift_days"]}
    for eid in p["event_ids"]:
        gws(["calendar", "events", "patch",
             "--params", json.dumps({"calendarId": "primary", "eventId": eid, "sendUpdates": "none"}),
             "--json", json.dumps(_event_times(p["start"], p["end"]))])
    return {"event_ids": p["event_ids"], "start": p["start"], "end": p["end"]}


def calendar_delete(event_id):
    gws(["calendar", "events", "delete",
         "--params", json.dumps({"calendarId": "primary", "eventId": event_id, "sendUpdates": "none"})])
    return {"deleted": event_id}


# ---------- gmail draft ----------
def draft_email(p):
    msg = EmailMessage()
    msg["To"] = p["to"]
    msg["Subject"] = p["subject"]
    msg.set_content(p["body"])
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = gws(["gmail", "users", "drafts", "create", "--params", json.dumps({"userId": "me"}),
             "--json", json.dumps({"message": {"raw": raw}})])  # drafts.create never sends
    return {"draft_id": r["id"]}


# ---------- ticket ----------
def _due_ms(due):
    return int(datetime.fromisoformat(due[:10]).replace(tzinfo=timezone.utc).timestamp() * 1000)


def ticket(p, backend=None):
    _load_env()
    token = os.environ.get("CLICKUP_API_TOKEN")
    backend = backend or ("clickup" if token else "gtasks")
    if backend == "clickup":
        if not token:
            return {"error": "no_clickup_token"}
        import httpx
        h = {"Authorization": token}
        if p.get("task_id"):  # due-date move on an existing task
            r = httpx.put(f"https://api.clickup.com/api/v2/task/{p['task_id']}", headers=h,
                          json={"due_date": _due_ms(p["due"])}, timeout=30)
        else:
            list_id = os.environ.get("CLICKUP_LIST_ID")
            if not list_id:
                return {"error": "no_clickup_list", "detail": "set CLICKUP_LIST_ID"}
            r = httpx.post(f"https://api.clickup.com/api/v2/list/{list_id}/task", headers=h,
                           json={"name": _prefixed(p["title"]), "description": p.get("description", ""),
                                 "due_date": _due_ms(p["due"])}, timeout=30)
        if r.status_code >= 300:
            return {"error": "clickup_failed", "detail": r.text[:200]}
        return {"task_id": r.json()["id"], "backend": "clickup"}
    # Google Tasks
    lst = {"tasklist": "@default"}
    due = p["due"][:10] + "T00:00:00.000Z"
    if p.get("task_id"):
        r = gws(["tasks", "tasks", "patch", "--params", json.dumps({**lst, "task": p["task_id"]}),
                 "--json", json.dumps({"due": due})])
    else:
        r = gws(["tasks", "tasks", "insert", "--params", json.dumps(lst),
                 "--json", json.dumps({"title": _prefixed(p["title"]), "notes": p.get("description", ""), "due": due})])
    return {"task_id": r["id"], "backend": "gtasks"}


def exists(event_id=None, task_id=None):
    """True when the calendar event or task exists and is not cancelled or deleted."""
    try:
        if event_id:
            r = gws(["calendar", "events", "get", "--params", json.dumps({"calendarId": "primary", "eventId": event_id})])
            return {"exists": r.get("status") != "cancelled"}
        r = gws(["tasks", "tasks", "get", "--params", json.dumps({"tasklist": "@default", "task": task_id})])
        return {"exists": not r.get("deleted", False)}
    except GwsError:
        return {"exists": False}


def task_delete(task_id):
    gws(["tasks", "tasks", "delete", "--params", json.dumps({"tasklist": "@default", "task": task_id})])
    return {"deleted": task_id}


# ---------- date-change extraction ----------
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_D = rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON}|{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?)"
RANGE_RE = re.compile(
    rf"(?:{_D}|(\d{{4}}-\d{{2}}-\d{{2}}))\s*(?:-|–|to|until|through)\s*(?:{_D}|(\d{{4}}-\d{{2}}-\d{{2}})|(\d{{1,2}}))",
    re.I)
TRIGGER_RE = re.compile(r"moved|postponed|rescheduled|pushed|shifted", re.I)


def _mk(y, mon, d):
    return date(y, MONTHS[mon[:3].lower()], int(d))


def regex_date_ranges(text, default_year=None):
    """Return list of {start,end} ISO ranges found in text, in order."""
    y = default_year or date.today().year
    out = []
    for m in RANGE_RE.finditer(text):
        g = m.groups()
        # first endpoint: groups 0-4 (d-mon, mon-d) and 4 iso; layout: [d1,mon1,mon1b,d1b, iso1, ...]
        try:
            s = _endpoint(g[0:5], y)
            e_groups = g[5:11]
            e = _endpoint(e_groups[0:5], y) if any(e_groups[0:5]) else None
            if e is None and e_groups[5]:
                e = s.replace(day=int(e_groups[5]))
            if s and e:
                if e < s:  # range crosses year end
                    e = e.replace(year=e.year + 1)
                if not g[4] and not default_year and s < date.today() - timedelta(days=60):
                    # "Jan 12-14" written in November means next January.
                    s, e = s.replace(year=s.year + 1), e.replace(year=e.year + 1)
                out.append({"start": s.isoformat(), "end": e.isoformat()})
        except (ValueError, TypeError):
            continue
    return out


def _endpoint(g, y):
    d1, mon1, mon2, d2, iso = g
    if iso:
        return date.fromisoformat(iso)
    if d1 and mon1:
        return _mk(y, mon1, d1)
    if mon2 and d2:
        return _mk(y, mon2, d2)
    return None


def _known_old():
    """Old trip dates from MARCO_TRIP_DATES ("YYYY-MM-DD:YYYY-MM-DD"), for mails that state only the new dates."""
    v = os.environ.get("MARCO_TRIP_DATES", "")
    if ":" not in v:
        return None
    a, b = v.split(":", 1)
    return {"start": a.strip(), "end": b.strip()}


def regex_extract(subject, body, known_old=None):
    # Body first: a subject like "moved to Jan 12-14" names only the new dates.
    text = f"{body}\n{subject}"
    if not TRIGGER_RE.search(text):
        return None
    ranges = regex_date_ranges(text)
    if len(ranges) >= 2:
        return {"old_dates": ranges[0], "new_dates": ranges[1]}
    if len(ranges) == 1 and known_old and ranges[0] != known_old:
        return {"old_dates": known_old, "new_dates": ranges[0]}
    return None


def llm_extract(subject, body):
    """Try Claude Haiku, else regex."""
    prompt = ("Extract the OLD and NEW date ranges of a rescheduled workshop. Reply with JSON only: "
              '{"old_dates":{"start":"YYYY-MM-DD","end":"YYYY-MM-DD"},"new_dates":{...}} or {} if none. '
              f"Today is {date.today().isoformat()}.\nSubject: {subject}\nBody: {body[:3000]}")
    known = _known_old()
    if known:
        prompt += f"\nIf the mail gives only the new dates, the old dates are {known['start']} to {known['end']}."
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            import httpx
            r = httpx.post("https://api.anthropic.com/v1/messages", timeout=30,
                           headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                           json={"model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"), "max_tokens": 300,
                                 "messages": [{"role": "user", "content": prompt}]})
            txt = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        else:
            return regex_extract(subject, body, _known_old())
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0)) if m else {}
        if d.get("old_dates") and d.get("new_dates"):
            return d
    except Exception:
        pass
    return regex_extract(subject, body, _known_old())


# ---------- watch-gmail ----------
def _processed():
    try:
        return set(json.loads(PROCESSED.read_text()))
    except Exception:
        return set()


def _save_processed(ids):
    DATA.mkdir(exist_ok=True)
    PROCESSED.write_text(json.dumps(sorted(ids)))


def _header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _body_text(payload):
    parts, stack = [], [payload]
    while stack:
        x = stack.pop()
        stack.extend(x.get("parts", []) or [])
        if x.get("mimeType") == "text/plain" and x.get("body", {}).get("data"):
            parts.append(base64.urlsafe_b64decode(x["body"]["data"] + "==").decode("utf-8", "replace"))
    return "\n".join(parts)


def watch_gmail(since, extract=llm_extract, trip_id=None):
    after = int(datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp())
    q = f'workshop (moved OR postponed OR rescheduled OR pushed) after:{after}'
    lst = gws(["gmail", "users", "messages", "list", "--params", json.dumps({"userId": "me", "q": q, "maxResults": 10})])
    seen, changes = _processed(), []
    for m in lst.get("messages", []) or []:
        if m["id"] in seen:
            continue
        msg = gws(["gmail", "users", "messages", "get", "--params", json.dumps({"userId": "me", "id": m["id"], "format": "full"})])
        subj, body = _header(msg, "Subject"), _body_text(msg.get("payload", {})) or msg.get("snippet", "")
        seen.add(m["id"])
        ex = extract(subj, body)
        if ex:
            changes.append({"message_id": m["id"], "subject": subj, **ex, "trip_id": trip_id or DEFAULT_TRIP})
    _save_processed(seen)
    return {"changes": changes}


# ---------- replan ----------
def read_audit(trip_id):
    try:
        p = subprocess.run(["uv", "run", "python", "-m", "services.audit", "list", "--trip", trip_id],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        if p.returncode == 0:
            return json.loads(p.stdout)["rows"]
    except Exception:
        pass
    rows = []
    f = DATA / "audit.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("trip_id") == trip_id:
                    rows.append(r)
    return rows


def _fmt(d):
    return f"{d['start']} to {d['end']}"


def build_replan(trip_id, change, rows):
    old, new = change["old_dates"], change["new_dates"]
    live = [r for r in rows if r.get("status") in ("done", "approved", "proposed")
            and r.get("act") != "replan"]
    superseded = {r.get("supersedes") for r in rows if r.get("supersedes")}
    live = [r for r in live if r["id"] not in superseded]
    by = lambda step: [r for r in live if r["step"] == step]
    shift = (_day(new["start"]) - _day(old["start"])).days
    actions, n = [], 0

    def add(step, cmd, args, supersedes, summary):
        nonlocal n
        n += 1
        actions.append({"n": n, "step": step, "cli": cmd, "args": args, "supersedes": supersedes, "summary": summary})

    for r in by("perk_submit") or by("perk_fill"):
        ref = r.get("external_ref")
        add("perk_cancel", "services.perk cancel", {"perk_trip": ref}, r["id"], "Cancel the Perk request for the old dates.")
        add("perk_fill", "services.perk plan",
            {"trip_id": trip_id, "depart": new["start"], "return": new["end"],
             "description": "HACKATHON TEST, DO NOT APPROVE. Replan after workshop date change."},
            r["id"], f"Plan a new Perk trip for {_fmt(new)}.")
    for r in by("calendar"):
        ids = [i for i in (r.get("external_ref") or "").split(",") if i]
        add("calendar", "services.gws calendar-move", {"event_ids": ids, "start": new["start"], "end": new["end"], "shift_days": shift},
            r["id"], f"Move the calendar block to {_fmt(new)}.")
    for r in by("uber_schedule"):
        add("uber_cancel", "services.uber cancel", {"ride": r.get("external_ref")}, r["id"], "Cancel the old Uber ride.")
        add("uber_schedule", "services.uber schedule",
            {"when_iso": f"{new['start']}T09:00:00", "shift_days": shift}, r["id"],
            f"Schedule a new Uber ride shifted by {shift} days.")
    for r in by("ticket"):
        add("ticket", "services.gws ticket", {"task_id": r.get("external_ref"), "due": new["start"]}, r["id"],
            f"Move the ticket due date to {new['start']}.")
    ref = (by("approval") or live or [{"id": None}])[-1]["id"]
    for who, env in (("the facilities approver", "APPROVER_EMAIL"), ("the client contact", "CLIENT_CONTACT_EMAIL")):
        add("email_draft", "services.gws draft-email",
            {"to": os.environ.get(env, f"{env.lower()}@example.invalid"),
             "subject": f"Workshop moved to {_fmt(new)}",
             "body": f"Hello,\n\nThe workshop moved from {_fmt(old)} to {_fmt(new)}. "
                     "I changed my travel plan to match.\n\nTokyo"},
            ref, f"Draft a note to {who} about the new dates (draft only).")
    text = (f"Trip: {trip_id}. The workshop moved from {_fmt(old)} to {_fmt(new)}. "
            f"Marco found {len(live)} active steps. Marco proposes {len(actions)} actions. Nothing runs until Tokyo approves.")
    return {"proposal": text, "actions": actions}


def replan(trip_id, change):
    return build_replan(trip_id, change, read_audit(trip_id))


# ---------- CLI ----------
def main(argv=None):
    _load_env()
    ap = argparse.ArgumentParser(prog="services.gws")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("calendar-block", "calendar-move", "draft-email", "ticket"):
        s = sub.add_parser(c)
        s.add_argument("--json", required=True)
        if c == "ticket":
            s.add_argument("--backend", choices=["clickup", "gtasks"])
    sub.add_parser("calendar-delete").add_argument("--event-id", required=True)
    sub.add_parser("calendar-event").add_argument("--json", required=True)
    sub.add_parser("task-delete").add_argument("--task-id", required=True)
    s = sub.add_parser("exists")
    s.add_argument("--event-id")
    s.add_argument("--task-id")
    sub.add_parser("watch-gmail").add_argument("--since", required=True)
    s = sub.add_parser("replan")
    s.add_argument("--trip", required=True)
    s.add_argument("--json", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "calendar-block":
            r = calendar_block(json.loads(a.json))
        elif a.cmd == "calendar-move":
            r = calendar_move(json.loads(a.json))
        elif a.cmd == "calendar-delete":
            r = calendar_delete(a.event_id)
        elif a.cmd == "calendar-event":
            r = calendar_event(json.loads(a.json))
        elif a.cmd == "task-delete":
            r = task_delete(a.task_id)
        elif a.cmd == "exists":
            r = exists(a.event_id, a.task_id)
        elif a.cmd == "draft-email":
            r = draft_email(json.loads(a.json))
        elif a.cmd == "ticket":
            r = ticket(json.loads(a.json), a.backend)
        elif a.cmd == "watch-gmail":
            r = watch_gmail(a.since)
        else:
            r = replan(a.trip, json.loads(a.json))
    except GwsError as e:
        print(json.dumps({"error": e.code, "detail": e.detail}))
        return 1
    except (KeyError, ValueError) as e:
        print(json.dumps({"error": "bad_input", "detail": str(e)}))
        return 1
    print(json.dumps(r))
    return 1 if "error" in r else 0


if __name__ == "__main__":
    sys.exit(main())
