"""Post a Marco proposal as one Slack Block Kit card, in the itinerary card style.

Run from the repo root:
  uv run python scripts/marco_card.py <options|clash|replan|cancel> --channel <id> --thread-ts <ts> --json '<facts>'

Facts per card (all strings unless noted):
  options: trip, dates, options[{label, flights, times, price, in_policy (bool), best (bool), note}],
           hotel, hotel_source, policy
  clash:   existing, new, options[{label, text}]
  replan:  trip, old_dates, new_dates, actions[{kind, text}]  kind: calendar|task|perk|uber|draft
  cancel:  traveller, actions[{kind, text}], free_cancel[str]
  done:    trip, items[{kind, text, status: done|held|failed, ref}]
  cancelled: traveller, items[{kind, text, ref}], next
  Any card: optional mention (slack id) and lead (one STE sentence) add a tag line under the header.
Prints {"ts": ...}. --dry-run prints the blocks and posts nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNEL = os.environ.get("MARCO_CHANNEL", "C0CKA55HJ31")
ICONS = {"calendar": "📅", "task": "✅", "perk": "✈️", "uber": "🚕", "draft": "✉️"}


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "emoji": True, "text": text[:150]}}


def _section(text: str, fields: list[str] | None = None) -> dict:
    block: dict = {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    if fields:
        block["fields"] = [{"type": "mrkdwn", "text": f} for f in fields[:10]]
    return block


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _divider() -> dict:
    return {"type": "divider"}


def _actions(actions: list[dict]) -> str:
    return "\n".join(f"{i}. {ICONS.get(a.get('kind', ''), '•')} {a['text']}" for i, a in enumerate(actions, 1))


def options_blocks(f: dict) -> list[dict]:
    blocks = [_header(f"✈️ {f['trip']} · {f['dates']}"), _divider()]
    for o in f["options"]:
        badge = "✅ In policy" if o.get("in_policy", True) else "⚠️ Out of policy"
        title = f"*Option {o['label']}*" + ("  ·  ⭐ *Best value*" if o.get("best") else "")
        fields = [f"*Flights*\n{o['flights']}", f"*Times*\n{o['times']}", f"*Price*\n{o['price']}", f"*Policy*\n{badge}"]
        blocks.append(_section(title, fields))
        if o.get("note"):
            blocks.append(_context(o["note"]))
    blocks.append(_divider())
    blocks.append(_context(f"🏨 {f['hotel']} (source: {f['hotel_source']}) · 📘 Policy: {f['policy']}"))
    best = next((o["label"] for o in f["options"] if o.get("best")), f["options"][0]["label"])
    blocks.append(_section(f"Reply `@Marco approve {best}`."))
    return blocks


def clash_blocks(f: dict) -> list[dict]:
    return [
        _header("⚠️ Clash"),
        _section("These trips overlap.", [f"*Existing trip*\n{f['existing']}", f"*New request*\n{f['new']}"]),
        _divider(),
        _section("\n".join(f"• *{o['label']})* {o['text']}" for o in f["options"])),
        _context("Nothing is booked."),
        _section("Reply `@Marco A`, `B` or `C`."),
    ]


def replan_blocks(f: dict) -> list[dict]:
    return [
        _header(f"🔁 Plan change · {f['trip']}"),
        _section(f"*{f['old_dates']}* → *{f['new_dates']}*"),
        _divider(),
        _section("*Actions*\n" + _actions(f["actions"])),
        _context("Nothing changes until you approve."),
        _section("Reply `@Marco approve`."),
    ]


def cancel_blocks(f: dict) -> list[dict]:
    blocks = [_header(f"🛑 Cancel trip for {f['traveller']}"), _divider(),
              _section("*Actions*\n" + _actions(f["actions"]))]
    if f.get("free_cancel"):
        blocks.append(_context(" · ".join(f"🆓 {n}" for n in f["free_cancel"])))
    blocks += [_context("Nothing changes until you approve."), _section("Reply `@Marco approve`.")]
    return blocks


STATUS_ICON = {"done": "✓", "held": "⏸", "failed": "✗", "cancelled": "✓", "browser_todo": "⏸", "proposed": "⏸"}
KIND_OF_STEP = {"calendar": "calendar", "ticket": "task", "perk_fill": "perk", "perk_cancel": "perk", "perk_submit": "perk",
                "uber_cancel": "uber", "uber_schedule": "uber", "email_draft": "draft"}


def done_blocks(f: dict) -> list[dict]:
    lines = [f"{STATUS_ICON.get(i['status'], '•')} {ICONS.get(i.get('kind', ''), '')} {i['text']}"
             + (f"  `{i['ref']}`" if i.get("ref") else "") for i in f["items"]]
    blocks = [_header(f"✅ Done · {f['trip']}"), _section("\n".join(lines))]
    if f.get("persona_url"):
        blocks.append({"type": "actions", "elements": [{"type": "button", "action_id": "persona_verify", "style": "primary",
                       "text": {"type": "plain_text", "emoji": True, "text": "🪪 Verify it's you (Persona)"},
                       "url": f["persona_url"]}]})
    return blocks + [_context("✓ done · ⏸ held or next · ✗ failed")]


def cancelled_blocks(f: dict) -> list[dict]:
    lines = [f"✓ {ICONS.get(i.get('kind', ''), '')} {i['text']}" + (f"  `{i['ref']}`" if i.get("ref") else "")
             for i in f["items"]]
    return [_header(f"🛑 Trip cancelled · {f['traveller']}"), _section("\n".join(lines)),
            _divider(), _section(f"*Next:* {f['next']}")]


def from_plan(trip: str, change: dict, plan: dict) -> dict:
    """Replan card facts from a services.gws or marco_ops replan plan."""
    fmt = lambda d: f"{d['start']} to {d['end']}"
    return {"trip": trip, "old_dates": fmt(change["old_dates"]), "new_dates": fmt(change["new_dates"]),
            "actions": [{"kind": KIND_OF_STEP.get(a["step"], ""), "text": a["summary"]} for a in plan["actions"]]}


def with_mention(blocks: list[dict], f: dict) -> list[dict]:
    if f.get("mention"):
        lead = f.get("lead", "")
        return [blocks[0], _section(f"<@{f['mention']}> {lead}".strip())] + blocks[1:]
    return blocks


def post(kind: str, facts: dict, channel: str, thread_ts: str | None = None) -> dict:
    from dotenv import load_dotenv
    import httpx

    load_dotenv(ROOT / ".env")
    body = {"channel": channel, "text": fallback_text(kind, facts),
            "blocks": with_mention(BUILDERS[kind](facts), facts), "unfurl_links": False}
    if thread_ts:
        body["thread_ts"] = thread_ts
    r = httpx.post("https://slack.com/api/chat.postMessage", json=body, timeout=30,
                   headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}).json()
    return {"ts": r["ts"]} if r.get("ok") else {"error": r.get("error")}


def fallback_text(kind: str, f: dict) -> str:
    """Plain text for notifications and clients that do not render blocks."""
    if kind == "options":
        return f"Trip options: {f['trip']}, {f['dates']}. Reply @Marco approve A."
    if kind == "clash":
        return "Clash: the new trip overlaps an existing trip. Reply @Marco A, B or C."
    if kind == "replan":
        return f"Plan change: {f['old_dates']} to {f['new_dates']}. Reply @Marco approve."
    if kind == "done":
        return f"Done: {f['trip']}."
    if kind == "cancelled":
        return f"Trip cancelled for {f['traveller']}."
    return f"Cancel trip for {f['traveller']}. Reply @Marco approve."


BUILDERS = {"options": options_blocks, "clash": clash_blocks, "replan": replan_blocks, "cancel": cancel_blocks,
            "done": done_blocks, "cancelled": cancelled_blocks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=sorted(BUILDERS))
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--thread-ts")
    ap.add_argument("--json", required=True, dest="facts")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    facts = json.loads(a.facts)
    if a.dry_run:
        print(json.dumps({"text": fallback_text(a.kind, facts), "blocks": with_mention(BUILDERS[a.kind](facts), facts)}))
        return 0
    r = post(a.kind, facts, a.channel, a.thread_ts)
    print(json.dumps(r))
    return 1 if "error" in r else 0


if __name__ == "__main__":
    sys.exit(main())
