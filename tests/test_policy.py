"""Tests for services.policy: local fallback and Senso response parsing."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.policy.__main__ import (
    QUOTE_MAX,
    SENSO_BASE_URL,
    ask_fallback,
    ask_senso,
    ingest_senso,
    main,
    parse_search_response,
)


# --- fallback ---------------------------------------------------------------


def test_fallback_finds_approval_rule():
    result = ask_fallback("who approves a trip?")
    assert result["backend"] == "fallback"
    assert "approve" in result["answer"].lower()
    assert result["citations"]
    for citation in result["citations"]:
        assert citation["ref"].startswith("docs/policy-summary.md#L")
        assert len(citation["quote"]) <= QUOTE_MAX


def test_fallback_finds_per_diem_rule():
    result = ask_fallback("does the per diem change with hotel breakfast?")
    assert "per diem" in result["answer"].lower()
    assert "breakfast" in result["answer"].lower()


def test_fallback_no_match_keeps_shape():
    result = ask_fallback("zzz qqq xyzzy")
    assert result["citations"] == []
    assert result["answer"]
    assert result["backend"] == "fallback"


def test_cli_ask_without_key_uses_fallback(monkeypatch, capsys):
    import services.policy.__main__ as policy_main
    monkeypatch.setattr(policy_main, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("SENSO_API_KEY", raising=False)
    exit_code = main(["ask", "--query", "which fares for long-haul flights?"])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["backend"] == "fallback"
    assert set(out) == {"answer", "citations", "backend"}


def test_cli_ingest_without_key_is_skipped(monkeypatch, capsys):
    import services.policy.__main__ as policy_main
    monkeypatch.setattr(policy_main, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("SENSO_API_KEY", raising=False)
    exit_code = main(["ingest"])
    assert exit_code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "skipped"


# --- Senso response parsing -------------------------------------------------


def test_parse_search_response_maps_and_truncates():
    data = {
        "answer": "Economy for short flights.",
        "results": [
            {"content_id": "c-1", "title": "Policy", "chunk_text": "x" * 500},
            {"content_id": "c-2", "title": "Policy", "chunk_text": "short quote"},
        ],
    }
    result = parse_search_response(data)
    assert result["answer"] == "Economy for short flights."
    assert result["backend"] == "senso"
    assert result["citations"][0] == {"ref": "c-1", "quote": "x" * QUOTE_MAX}
    assert result["citations"][1] == {"ref": "c-2", "quote": "short quote"}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ask_senso_with_mocked_http():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == f"{SENSO_BASE_URL}/org/search"
        assert request.headers["X-API-Key"] == "test-key"
        assert json.loads(request.content) == {"query": "who approves?"}
        return httpx.Response(
            200,
            json={
                "answer": "Facilities approve the trip.",
                "results": [
                    {"content_id": "doc-1", "chunk_text": "Facilities approve the trip."}
                ],
            },
        )

    with _client(handler) as client:
        result = ask_senso("who approves?", "test-key", client)
    assert result["answer"] == "Facilities approve the trip."
    assert result["citations"] == [
        {"ref": "doc-1", "quote": "Facilities approve the trip."}
    ]


def test_ask_senso_http_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad key"})

    with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            ask_senso("q", "bad-key", client)


def test_ingest_senso_polls_until_complete():
    calls = {"nodes": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                202, json={"id": "content-1", "kb_node_id": "node-1"}
            )
        calls["nodes"] += 1
        status = "processing" if calls["nodes"] < 2 else "complete"
        return httpx.Response(
            200, json={"kb_node_id": "node-1", "content": {"processing_status": status}}
        )

    with _client(handler) as client:
        result = ingest_senso("test-key", client, poll_interval_s=0)
    assert result == {"status": "complete", "kb_node_id": "node-1", "backend": "senso"}
    assert calls["nodes"] == 2


def test_ingest_senso_409_means_already_ingested():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "duplicate"})

    with _client(handler) as client:
        result = ingest_senso("test-key", client)
    assert result["status"] == "already_ingested"
