from __future__ import annotations

import json
from typing import Any

from services.router.client import ChatBackend, complete_with_fallback
from services.router.ledger import append_event
from services.router.pricing import cost_usd
from services.router.tier import pick_tier

_RANK_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "rank_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "choice": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["choice", "reason"],
            "additionalProperties": False,
        },
    },
}


def _heuristic_rank(task: str, options: list[Any], facts: list[Any]) -> dict[str, Any]:
    opts = [str(o) for o in (options or [])]
    choice = opts[0] if opts else (task[:80] or "none")
    fact_ref = ""
    if facts:
        fact_ref = str(facts[0])[:120]
    reason = f"I pick {choice} because it matches the first fact: {fact_ref}." if fact_ref else (
        f"I pick {choice} because it is the first listed option for this task."
    )
    return {"choice": choice, "reason": reason[:500]}


def _build_messages(task: str, options: list[Any], facts: list[Any]) -> list[dict[str, str]]:
    opts = options or []
    fact_lines = "\n".join(f"- {f}" for f in (facts or [])) or "- (none)"
    opt_lines = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(opts)) or "(none)"
    system = (
        "You are Marco's router. Pick one option using the facts. "
        "Return JSON with choice and reason. Use one short STE sentence for reason."
    )
    user = (
        f"Task: {task}\n\nFacts:\n{fact_lines}\n\nOptions:\n{opt_lines}\n\n"
        "Set choice to the exact option text you select."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def rank_task(
    payload: dict[str, Any],
    backend: ChatBackend | None,
) -> dict[str, Any]:
    task = str(payload.get("task") or "")
    options = payload.get("options") or []
    facts = payload.get("facts") or []
    session_id = str(payload.get("session_id") or "")
    trip_id = str(payload.get("trip_id") or "")

    tier = pick_tier(task, options)

    try:
        messages = _build_messages(task, options, facts)
        result = complete_with_fallback(
            backend,
            tier=tier,
            messages=messages,
            response_format=_RANK_SCHEMA if tier == "large" else None,
        )
        parsed = json.loads(result.content) if result.content.strip().startswith("{") else {}
        if not parsed:
            parsed = _heuristic_rank(task, options, facts)
        choice = str(parsed.get("choice") or _heuristic_rank(task, options, facts)["choice"])
        reason = str(parsed.get("reason") or _heuristic_rank(task, options, facts)["reason"])
        cost = cost_usd(
            provider=result.provider,
            model=result.model,
            tier=tier,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        append_event(
            session_id=session_id,
            trip_id=trip_id,
            provider=result.provider,
            model=result.model,
            tier=tier,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=cost,
        )
        return {
            "choice": choice,
            "reason": reason,
            "model": result.model,
            "tier": tier,
            "cost_usd": round(cost, 8),
        }
    except RuntimeError as exc:
        if str(exc) != "no_api_key":
            raise
        picked = _heuristic_rank(task, options, facts)
        model = "heuristic"
        append_event(
            session_id=session_id,
            trip_id=trip_id,
            provider="local",
            model=model,
            tier=tier,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )
        return {
            "choice": picked["choice"],
            "reason": picked["reason"],
            "model": model,
            "tier": tier,
            "cost_usd": 0.0,
        }