"""Apply the pending replan after Tokyo replies "approve" in its thread.

Usage (repo root):
  uv run python scripts/marco_apply_replan.py --approved-by <slack member id>

Reads data/replan_pending.json (written by scripts/marco_watch.py).
Runs: calendar-move, ticket due-date move, email drafts (drafts only, never sent).
Returns browser_todo for Perk (change draft dates) and Uber (cancel, reserve again). Marco runs them next.
Every action writes one audit row with act=replan and supersedes set.
Prints one JSON summary.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "anthropic/claude-sonnet-5-5"
RUN = {"calendar": "calendar-move", "ticket": "ticket", "email_draft": "draft-email"}
HELD = {"perk_cancel", "perk_fill", "perk_submit", "uber_cancel", "uber_schedule"}


def cli(module: str, *args: str) -> dict:
    p = subprocess.run(["uv", "run", "python", "-m", module, *args], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"error": "bad_output"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approved-by", required=True)
    ap.add_argument("--post", action="store_true", help="post the Done card in the replan thread")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT / "scripts"))
    from marco_ops import NotOwner, require_owner

    try:
        require_owner(a.approved_by)
    except NotOwner as e:
        print(json.dumps({"error": "not_owner", "detail": str(e)}))
        return 1
    pending = json.loads((ROOT / "data" / "replan_pending.json").read_text())
    trip, change = pending["change"]["trip_id"], pending["change"]
    src = [{"type": "gmail", "ref": change.get("message_id", ""), "quote": change.get("subject", "")[:200]}]
    results = []

    cli("services.audit", "record", "--json", json.dumps({
        "trip_id": trip, "act": "replan", "step": "approval", "status": "approved",
        "summary": "Tokyo approved the replan.", "sources": [{"type": "slack", "ref": pending.get("thread_ts") or "", "quote": "approve"}],
        "model": MODEL, "cost_usd": 0.0, "external_ref": pending.get("thread_ts"), "supersedes": None,
        "approved_by": a.approved_by}))

    for act in pending["plan"]["actions"]:
        step, args = act["step"], act["args"]
        if step in RUN:
            extra = ["--backend", "gtasks"] if step == "ticket" else []
            r = cli("services.gws", RUN[step], *extra, "--json", json.dumps(args))
            ok = "error" not in r
            ref = ",".join(r.get("event_ids", [])) or r.get("task_id") or r.get("draft_id")
            status, summary = ("done" if ok else "failed"), (act["summary"] if ok else f"Failed: {act['summary']}")
        elif step in HELD:
            results.append({"n": act["n"], "step": step, "status": "browser_todo", "summary": act["summary"]})
            continue
        else:
            continue
        cli("services.audit", "record", "--json", json.dumps({
            "trip_id": trip, "act": "replan", "step": step, "status": status, "summary": summary[:200],
            "sources": src, "model": MODEL, "cost_usd": 0.0, "external_ref": ref,
            "supersedes": act.get("supersedes"), "approved_by": a.approved_by}))
        results.append({"n": act["n"], "step": step, "status": status, "summary": summary})

    out = {"trip_id": trip, "new_dates": change["new_dates"], "results": results}
    if a.post:
        import marco_card as mc
        status = {"done": "done", "failed": "failed"}
        items = [{"kind": mc.KIND_OF_STEP.get(r["step"], ""), "text": r["summary"],
                  "status": status.get(r["status"], "held")} for r in results]
        out["card"] = mc.post("done", {"trip": trip, "items": items, "mention": a.approved_by,
                                       "lead": "Calendar, task and drafts updated. Perk and Uber steps run next."},
                              pending.get("channel") or "C0CLLEH6D1N", pending.get("thread_ts"))
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
