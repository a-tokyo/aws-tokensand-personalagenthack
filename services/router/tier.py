from __future__ import annotations

import re

_SIMPLE = re.compile(
    r"\b(format|formatting|extract|extraction|classif|classify|parse|convert|tag|label)\b",
    re.IGNORECASE,
)


def pick_tier(task: str, options: list | None) -> str:
    """Pareto tier: small for cheap simple work, large for option ranking."""
    opts = options or []
    if len(opts) > 0:
        return "large"
    text = (task or "").strip()
    if _SIMPLE.search(text):
        return "small"
    if len(text) <= 120:
        return "small"
    return "large"