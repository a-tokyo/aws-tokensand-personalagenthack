from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_PRICES_PATH = Path(__file__).resolve().parent / "prices.json"


def load_prices() -> dict[str, Any]:
    path = Path(os.environ.get("ROUTER_PRICES_PATH", str(_PRICES_PATH)))
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data


def _env_rate(prefix: str, field: str) -> float | None:
    key = f"{prefix}_{field.upper()}"
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return None
    return float(raw)


def rates_for(provider: str, model: str, tier: str) -> tuple[float, float]:
    """Return (input_per_million, output_per_million) USD."""
    tier_in = _env_rate(f"ROUTER_{tier.upper()}", "input_price_per_million")
    tier_out = _env_rate(f"ROUTER_{tier.upper()}", "output_price_per_million")
    if tier_in is not None and tier_out is not None:
        return tier_in, tier_out

    data = load_prices()
    models = data.get("models") or {}
    if model in models:
        m = models[model]
        return float(m["input_per_million"]), float(m["output_per_million"])

    providers = data.get("providers") or {}
    if provider in providers:
        p = providers[provider]
        return float(p["input_per_million"]), float(p["output_per_million"])

    return float(data["default_input_per_million"]), float(data["default_output_per_million"])


def cost_usd(
    *,
    provider: str,
    model: str,
    tier: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    inp_rate, out_rate = rates_for(provider, model, tier)
    return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000.0