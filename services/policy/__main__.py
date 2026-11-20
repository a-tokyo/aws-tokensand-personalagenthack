"""Policy service CLI (lane L9).

Commands:
  ingest            Post docs/policy-summary.md to the Senso knowledge base.
  ask --query "<q>" Ask the policy a question. Uses Senso when SENSO_API_KEY is
                    set. Falls back to a local keyword search when it is not.

Every command prints one JSON object to stdout. Errors exit 1 with
{"error": "<code>", "detail": "<text>"}.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_DOC = REPO_ROOT / "docs" / "policy-summary.md"
SENSO_BASE_URL = "https://apiv2.senso.ai/api/v1"
DOC_TITLE = "Travel policy summary (sanitised)"
QUOTE_MAX = 200
POLL_INTERVAL_S = 5.0
POLL_TIMEOUT_S = 120.0

_STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "how", "i", "in",
    "is", "it", "my", "of", "on", "or", "the", "to", "what", "when", "where",
    "which", "who", "with",
}


def _headers(api_key: str) -> dict:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


def ingest_senso(
    api_key: str,
    client: httpx.Client,
    base_url: str = SENSO_BASE_URL,
    poll_interval_s: float = POLL_INTERVAL_S,
    poll_timeout_s: float = POLL_TIMEOUT_S,
) -> dict:
    """Post the policy doc to Senso and wait until it is processed."""
    text = POLICY_DOC.read_text()
    resp = client.post(
        f"{base_url}/org/kb/raw",
        headers=_headers(api_key),
        json={"title": DOC_TITLE, "text": text},
    )
    if resp.status_code == 409:
        return {"status": "already_ingested", "backend": "senso"}
    resp.raise_for_status()
    node_id = resp.json()["kb_node_id"]

    deadline = time.monotonic() + poll_timeout_s
    while True:
        node = client.get(f"{base_url}/org/kb/nodes/{node_id}", headers=_headers(api_key))
        node.raise_for_status()
        content = node.json().get("content", {})
        status = content.get("processing_status")
        if status == "complete":
            return {"status": "complete", "kb_node_id": node_id, "backend": "senso"}
        if status == "failed":
            raise RuntimeError(f"senso processing failed: {content.get('error_code')}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"senso processing did not complete for node {node_id}")
        time.sleep(poll_interval_s)


def parse_search_response(data: dict) -> dict:
    """Map a Senso /org/search response to the contracts.md shape."""
    citations = [
        {
            "ref": result.get("content_id") or result.get("title", ""),
            "quote": (result.get("chunk_text") or "")[:QUOTE_MAX],
        }
        for result in data.get("results", [])
    ]
    return {"answer": data.get("answer", ""), "citations": citations, "backend": "senso"}


def ask_senso(
    query: str,
    api_key: str,
    client: httpx.Client,
    base_url: str = SENSO_BASE_URL,
) -> dict:
    resp = client.post(
        f"{base_url}/org/search",
        headers=_headers(api_key),
        json={"query": query},
    )
    resp.raise_for_status()
    return parse_search_response(resp.json())


def ask_fallback(query: str, doc_path: Path = POLICY_DOC) -> dict:
    """Keyword search over the local policy doc. Same output shape as Senso."""
    terms = {
        word
        for word in re.findall(r"[a-z0-9]+", query.lower())
        if word not in _STOPWORDS
    }
    scored = []
    for line_no, line in enumerate(doc_path.read_text().splitlines(), start=1):
        stripped = line.strip().lstrip("-# ").strip()
        if not stripped:
            continue
        line_words = set(re.findall(r"[a-z0-9]+", stripped.lower()))
        score = len(terms & line_words)
        if score > 0:
            scored.append((score, line_no, stripped))
    scored.sort(key=lambda item: (-item[0], item[1]))
    top = scored[:3]
    if not top:
        return {
            "answer": "The policy summary has no rule that matches this query.",
            "citations": [],
            "backend": "fallback",
        }
    return {
        "answer": " ".join(text for _, _, text in top),
        "citations": [
            {"ref": f"docs/policy-summary.md#L{line_no}", "quote": text[:QUOTE_MAX]}
            for _, line_no, text in top
        ],
        "backend": "fallback",
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(prog="services.policy")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest")
    ask_parser = sub.add_parser("ask")
    ask_parser.add_argument("--query", required=True)
    args = parser.parse_args(argv)

    api_key = os.environ.get("SENSO_API_KEY", "").strip()
    try:
        if args.command == "ingest":
            if not api_key:
                result = {
                    "status": "skipped",
                    "backend": "fallback",
                    "detail": "SENSO_API_KEY is not set; ask will use the local fallback",
                }
            else:
                with httpx.Client(timeout=30.0) as client:
                    result = ingest_senso(api_key, client)
        else:
            if not api_key:
                result = ask_fallback(args.query)
            else:
                with httpx.Client(timeout=30.0) as client:
                    result = ask_senso(args.query, api_key, client)
    except Exception as exc:  # noqa: BLE001 - CLI boundary, contract error shape
        print(json.dumps({"error": "policy_error", "detail": str(exc)}))
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
