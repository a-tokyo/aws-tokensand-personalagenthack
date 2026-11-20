"""Post a Marco proposal as one Slack Block Kit card, in the itinerary card style.

Run from the repo root:
  uv run python scripts/marco_card.py <options|clash|replan|cancel> --channel <id> --thread-ts <ts> --json '<facts>'

Facts per card (all strings unless noted):
  options: trip, dates, options[{label, flights, times, price, in_policy (bool), best (bool), note}],
           hotel, hotel_source, policy
  clash:   existing, new, options[{label, text}]
  replan:  trip, old_dates, new_dates, actions[{kind, text}]  kind: calendar|task|perk|uber|draft
  cancel:  traveller, actions[{kind, text}], free_cancel[str]
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


def fallback_text(kind: str, f: dict) -> str:
    """Plain text for notifications and clients that do not render blocks."""
    if kind == "options":
        return f"Trip options: {f['trip']}, {f['dates']}. Reply @Marco approve A."
    if kind == "clash":
        return "Clash: the new trip overlaps an existing trip. Reply @Marco A, B or C."
    if kind == "replan":
        return f"Plan change: {f['old_dates']} to {f['new_dates']}. Reply @Marco approve."
    return f"Cancel trip for {f['traveller']}. Reply @Marco approve."


BUILDERS = {"options": options_blocks, "clash": clash_blocks, "replan": replan_blocks, "cancel": cancel_blocks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=sorted(BUILDERS))
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--thread-ts")
    ap.add_argument("--json", required=True, dest="facts")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    facts = json.loads(a.facts)
    blocks, text = BUILDERS[a.kind](facts), fallback_text(a.kind, facts)
    if a.dry_run:
        print(json.dumps({"text": text, "blocks": blocks}))
        return 0
    from dotenv import load_dotenv
    import httpx

    load_dotenv(ROOT / ".env")
    body = {"channel": a.channel, "text": text, "blocks": blocks, "unfurl_links": False}
    if a.thread_ts:
        body["thread_ts"] = a.thread_ts
    r = httpx.post("https://slack.com/api/chat.postMessage", json=body, timeout=30,
                   headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}).json()
    if not r.get("ok"):
        print(json.dumps({"error": r.get("error")}))
        return 1
    print(json.dumps({"ts": r["ts"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
