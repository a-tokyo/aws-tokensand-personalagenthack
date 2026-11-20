"""Send one connected check to Tokens& for Marco's Novato pipeline.

Runs the real service CLIs (memory recall, policy ask, router rank) on the
Novato request. Each CLI call is one traced tool span. Each case asserts on the
CLI's JSON output. The exit code is 1 if any case fails.

Setup: download the SDK wheel from the Tokens& Build & Evaluate page into
vendor/tokensand/ (see vendor/tokensand/README.md), and put
TOKENS_OBSERVE_API_KEY and TOKENS_OBSERVE_INGEST_URL in .env.

Run: uv run --with vendor/tokensand/tokensand_observe-0.6.15-py3-none-any.whl \
         python scripts/tokensand_check.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from tokensand_observe import Observer

ROOT = Path(__file__).resolve().parents[1]
REQUEST = "Plan the trip to Novato for Bart's AI workshop, 30 Nov to 2 Dec."


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def cli(*args: str) -> dict:
    proc = subprocess.run(
        ["uv", "run", "python", "-m", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    if proc.returncode != 0 or "error" in out:
        raise RuntimeError(f"{args[0]} failed: {out.get('error', proc.returncode)}")
    return out


def main() -> int:
    load_env()
    session = str(uuid.uuid4())
    results: dict[str, bool] = {}
    with Observer(
        endpoint=os.environ["TOKENS_OBSERVE_INGEST_URL"],
        api_key=os.environ["TOKENS_OBSERVE_API_KEY"],
    ) as obs:
        def case(name: str, tool: str, fn, check) -> object:
            try:
                with obs.tool(session, tool):
                    out = fn()
                    ok = bool(check(out))
                    if not ok:
                        raise AssertionError(name)
            except Exception as exc:  # noqa: BLE001 - report each case
                print(f"FAIL {name}: {type(exc).__name__}")
                results[name] = False
                return None
            print(f"PASS {name}")
            results[name] = True
            return out

        recall = case(
            "recall_hotel", "memory_recall",
            lambda: cli("services.memory", "recall", "--query", REQUEST),
            lambda o: any("novato" in f["fact"].lower() for f in o["facts"]),
        )
        case(
            "policy_business_class", "policy_ask",
            lambda: cli("services.policy", "ask", "--query",
                        "Is business class allowed on a flight from Porto to San Francisco?"),
            lambda o: o["answer"].strip() != "",
        )
        facts = [f["fact"] for f in (recall or {}).get("facts", [])]
        options = [
            {"id": "A", "label": "TAP economy 07:00", "price_eur": 1100, "duration_h": 14},
            {"id": "B", "label": "TAP business 07:00", "price_eur": 4700, "duration_h": 13},
        ]
        ranked = case(
            "rank_options", "router_rank",
            lambda: cli("services.router", "rank", "--json",
                        json.dumps({"task": REQUEST, "options": options, "facts": facts})),
            lambda o: bool(o.get("choice")) and bool(o.get("reason")),
        )
        if ranked:
            # The rank step is the one model call; report it as a request.
            provider, _, model = str(ranked.get("model") or "anthropic/claude-sonnet-5-5").rpartition("/")
            provider = provider or "anthropic"
            with obs.observe(provider=provider, model=model, feature="rank",
                             session_id=session) as m:
                m.complete(status=200)
        delivery = obs.flush(timeout=10)
    print(json.dumps({"cases": results, "delivery_complete": delivery["complete"]}))
    return 0 if all(results.values()) and delivery["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
