from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_ROOT = Path(os.environ.get("ROUTER_LEDGER_DIR", str(REPO_ROOT / "data" / "ledger" / "events")))


def _ledger_path(day: date) -> Path:
    return LEDGER_ROOT / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}.jsonl"


def make_event_id(session_id: str, day: date, provider: str, model: str) -> str:
    raw = f"{session_id}|{day.isoformat()}|{provider}|{model}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def append_event(
    *,
    session_id: str,
    trip_id: str,
    provider: str,
    model: str,
    tier: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    day: date | None = None,
) -> dict[str, Any]:
    day = day or datetime.now(timezone.utc).date()
    event_id = make_event_id(session_id, day, provider, model)
    row: dict[str, Any] = {
        "event_id": event_id,
        "date": day.isoformat(),
        "agent_id": "marco",
        "session_id": session_id or "",
        "trip_id": trip_id or "",
        "provider": provider,
        "model": model,
        "tier": tier,
        "requests": 1,
        "tokens": {"input": input_tokens, "output": output_tokens},
        "cost_usd": round(cost_usd, 8),
        "cost_basis": "provider-usage",
    }
    path = _ledger_path(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def report_for_date(day: date) -> dict[str, Any]:
    path = _ledger_path(day)
    by_trip: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    by_tier: dict[str, float] = defaultdict(float)
    total = 0.0
    if path.is_file():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                cost = float(row.get("cost_usd") or 0)
                total += cost
                trip = row.get("trip_id") or "(none)"
                by_trip[trip] += cost
                by_model[row.get("model") or "unknown"] += cost
                by_tier[row.get("tier") or "unknown"] += cost
    return {
        "date": day.isoformat(),
        "total_usd": round(total, 8),
        "by_trip": {k: round(v, 8) for k, v in sorted(by_trip.items())},
        "by_model": {k: round(v, 8) for k, v in sorted(by_model.items())},
        "by_tier": {k: round(v, 8) for k, v in sorted(by_tier.items())},
    }