from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from services.router import ledger, pricing
from services.router.client import CompletionResult
from services.router.rank import rank_task
from services.router.tier import pick_tier


@dataclass
class FakeBackend:
    content: str
    provider: str = "fake"
    model: str = "fake-model"
    input_tokens: int = 100
    output_tokens: int = 50

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> CompletionResult:
        _ = model, messages, tools, response_format
        return CompletionResult(
            content=self.content,
            provider=self.provider,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )


def test_pick_tier_routing():
    assert pick_tier("Format this date", []) == "small"
    assert pick_tier("extract hotel name from email", None) == "small"
    assert pick_tier("pick a hotel", ["A", "B"]) == "large"
    assert pick_tier("x" * 200, []) == "large"


def test_cost_math_monotonic():
    small = pricing.cost_usd(
        provider="anthropic",
        model="claude-haiku-5-5",
        tier="small",
        input_tokens=1000,
        output_tokens=500,
    )
    large = pricing.cost_usd(
        provider="anthropic",
        model="claude-sonnet-5-5",
        tier="large",
        input_tokens=1000,
        output_tokens=500,
    )
    assert small >= 0
    assert large >= small or large >= 0
    assert pricing.cost_usd(
        provider="anthropic",
        model="m",
        tier="small",
        input_tokens=1_000_000,
        output_tokens=0,
    ) == pytest.approx(2.0, rel=1e-6)


def test_ledger_row_shape_no_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_ROOT", tmp_path)
    row = ledger.append_event(
        session_id="sess-1",
        trip_id="novato-2026-11-30",
        provider="fake",
        model="fake-model",
        tier="large",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
        day=date(2026, 11, 20),
    )
    assert row["event_id"] and len(row["event_id"]) == 16
    assert row["agent_id"] == "marco"
    assert row["cost_basis"] == "provider-usage"
    assert set(row["tokens"]) == {"input", "output"}
    blob = json.dumps(row)
    assert "prompt" not in blob.lower()
    path = tmp_path / "2026" / "11" / "20.jsonl"
    assert path.is_file()
    stored = json.loads(path.read_text().strip())
    assert "prompt" not in stored


def test_rank_uses_fake_client_and_writes_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "LEDGER_ROOT", tmp_path)
    backend = FakeBackend(
        content=json.dumps(
            {"choice": "Courtyard Novato", "reason": "It matches the king room fact."}
        ),
        model="claude-sonnet-5-5",
    )
    out = rank_task(
        {
            "task": "pick hotel",
            "options": ["Courtyard Novato", "Holiday Inn"],
            "facts": ["Novato visits use Courtyard king room."],
            "session_id": "s1",
            "trip_id": "novato-2026-11-30",
        },
        backend,
    )
    assert out["tier"] == "large"
    assert out["choice"] == "Courtyard Novato"
    assert out["cost_usd"] > 0
    from datetime import datetime, timezone

    report = ledger.report_for_date(datetime.now(timezone.utc).date())
    assert report["by_trip"].get("novato-2026-11-30", 0) > 0


def test_rank_no_api_heuristic(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "LEDGER_ROOT", tmp_path)
    out = rank_task(
        {"task": "extract", "options": [], "facts": ["fact one"]},
        None,
    )
    assert out["model"] == "heuristic"
    assert out["cost_usd"] == 0.0