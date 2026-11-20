"""Superlinked SIE Serverless reranker for memory recall.

POST {SIE_BASE_URL}/v1/score/{model} with a query and candidate items.
SIE returns a relevance score per item. On any failure we keep the input order.
"""
import os

import httpx

BASE_URL = "https://api.superlinked.com"
MODEL = "Qwen/Qwen3-Reranker-4B"


def rerank(query: str, facts: list[dict], client: httpx.Client | None = None) -> tuple[list[dict], str]:
    """Return (facts sorted by SIE score with `sie_score`, reranker name).

    Reranker name is "superlinked-sie" on success, else "none" with the order unchanged.
    """
    key = os.getenv("SIE_API_KEY")
    if not key or not facts:
        return facts, "none"
    base = os.getenv("SIE_BASE_URL", BASE_URL).rstrip("/")
    model = os.getenv("SIE_RERANK_MODEL", MODEL)
    body = {"query": {"text": query}, "items": [{"id": str(i), "text": f["fact"]} for i, f in enumerate(facts)]}
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        r = client.post(f"{base}/v1/score/{model}", json=body, headers=headers)
        r.raise_for_status()
        scores = {s["item_id"]: float(s["score"]) for s in r.json()["scores"]}
        if len(scores) != len(facts):
            return facts, "none"
    except Exception:
        return facts, "none"
    finally:
        if own:
            client.close()
    out = [{**f, "sie_score": round(scores[str(i)], 4)} for i, f in enumerate(facts)]
    out.sort(key=lambda f: -f["sie_score"])
    return out, "superlinked-sie"
