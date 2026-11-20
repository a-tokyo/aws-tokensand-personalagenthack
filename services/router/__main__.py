from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from services.router.client import (
    build_primary_backend,
    complete_with_fallback,
    list_models_http,
)
from services.router.ledger import report_for_date
from services.router.rank import rank_task

REPO_ROOT = Path(__file__).resolve().parents[2]


def _emit_ok(payload: dict) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def _emit_error(code: str, detail: str) -> None:
    print(json.dumps({"error": code, "detail": detail}))
    sys.exit(1)


def cmd_rank(args: argparse.Namespace) -> None:
    try:
        payload = json.loads(args.json)
    except json.JSONDecodeError as exc:
        _emit_error("invalid_json", str(exc))
    backend = build_primary_backend()
    _emit_ok(rank_task(payload, backend))


def cmd_models(_: argparse.Namespace) -> None:
    try:
        models = list_models_http()
    except Exception as exc:  # noqa: BLE001
        _emit_error("models_failed", str(exc))
    if not models:
        _emit_error(
            "no_api_key",
            "Set ANTHROPIC_API_KEY to list models.",
        )
    ids = []
    for m in models:
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if mid:
            ids.append(mid)
    _emit_ok({"models": ids})


def cmd_ledger_report(args: argparse.Namespace) -> None:
    try:
        day = date.fromisoformat(args.date)
    except ValueError:
        _emit_error("invalid_date", "Use YYYY-MM-DD.")
    _emit_ok(report_for_date(day))


def cmd_tool_check(_: argparse.Namespace) -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "echo_ping",
                "description": "Acknowledge the health check.",
                "parameters": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["ok"]}},
                    "required": ["status"],
                },
            },
        }
    ]
    messages = [{"role": "user", "content": "Call echo_ping with status ok."}]
    backend = build_primary_backend()
    try:
        result = complete_with_fallback(
            backend, tier="large", messages=messages, tools=tools
        )
    except RuntimeError as exc:
        if str(exc) == "no_api_key":
            _emit_error(
                "no_api_key",
                "Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY for tool-check.",
            )
        _emit_error("tool_check_failed", str(exc))
    except Exception as exc:  # noqa: BLE001
        _emit_error("tool_check_failed", str(exc))

    valid = False
    msg = result.raw_message
    if msg is not None:
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", None) if fn else None
            if name == "echo_ping":
                valid = True
                break
    _emit_ok(
        {
            "tool_call_valid": valid,
            "model": result.model,
            "provider": result.provider,
        }
    )


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(prog="services.router")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rank = sub.add_parser("rank")
    p_rank.add_argument("--json", required=True)
    p_rank.set_defaults(func=cmd_rank)

    p_models = sub.add_parser("models")
    p_models.set_defaults(func=cmd_models)

    p_ledger = sub.add_parser("ledger-report")
    p_ledger.add_argument("--date", required=True)
    p_ledger.set_defaults(func=cmd_ledger_report)

    p_tool = sub.add_parser("tool-check")
    p_tool.set_defaults(func=cmd_tool_check)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()