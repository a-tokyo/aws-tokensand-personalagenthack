import json

from services.memory import core, kb

FACTS = [
    {"fact": "Tokyo books room only in Novato and buys breakfast himself.", "topic": "habit", "place": "Novato", "source_ref": "slack:1"},
    {"fact": "Dublin hotel is The Dean on Harcourt Street.", "topic": "hotel", "place": "Dublin", "source_ref": "gmail:2"},
]


def test_fallback_recall_cites_source():
    out = core.fallback_recall("where does he stay in Dublin hotel", facts=FACTS)
    assert out["backend"] == "fallback"
    assert out["facts"][0]["source_ref"] == "gmail:2"


def test_fallback_recall_no_match():
    assert core.fallback_recall("zzz qqq", facts=FACTS)["facts"] == []


def test_parse_cognee_tags():
    res = core._parse(["[src:slack:1] Tokyo books room only."], [])
    assert res[0]["source_ref"] == "slack:1" and res[0]["fact"] == "Tokyo books room only."


def test_kb_append_creates_then_updates(tmp_path):
    e = {"trip_id": "Novato Jan", "title": "Novato January", "action": "perk-plan", "status": "proposed",
         "summary": "Plan ready, ref 12345678", "place": "Novato"}
    kb.kb_write(e, root=tmp_path)
    kb.kb_write({**e, "status": "done"}, root=tmp_path)
    page = (tmp_path / "wiki/trips/novato-jan.md").read_text()
    assert page.count("perk-plan") == 2 and "[[places/novato]]" in page
    assert "12345678" not in page
    log = (tmp_path / "log.md").read_text()
    assert log.count("novato-jan") == 2


def test_build_vault(tmp_path):
    kb.build_vault(root=tmp_path)
    assert (tmp_path / ".obsidian/core-plugins.json").exists()
    assert "[[wiki/traveller/tokyo]]" in (tmp_path / "index.md").read_text()
    json.loads((tmp_path / ".obsidian/graph.json").read_text())


def test_parse_drops_warming_status_and_cites_by_overlap():
    idx = [{"fact": "Tokyo stays at The Dean Dublin Centre on Harcourt Street.", "source_ref": "gmail:9"}]
    assert core._parse([{"status": "memory_warming_up"}], idx) == []
    out = core._parse([{"text": "Tokyo stays at The Dean Dublin Centre on Harcourt Street. Confirm early."}], idx)
    assert out[0]["source_ref"] == "gmail:9"


def test_local_graph_has_nodes():
    from services.memory import graphviz
    g = graphviz.build()
    assert len(g["nodes"]) > 10 and g["edges"]


def _sie_client(handler):
    import httpx
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sie_rerank_sorts_by_score(monkeypatch):
    from services.memory import sie
    monkeypatch.setenv("SIE_API_KEY", "test")
    seen = {}

    def handler(req):
        seen["url"], seen["body"] = str(req.url), json.loads(req.content)
        return __import__("httpx").Response(200, json={"scores": [
            {"item_id": "1", "score": 0.9, "rank": 0}, {"item_id": "0", "score": 0.1, "rank": 1}]})

    out, name = sie.rerank("Novato breakfast", FACTS, client=_sie_client(handler))
    assert name == "superlinked-sie"
    assert [f["source_ref"] for f in out] == ["gmail:2", "slack:1"] and out[0]["sie_score"] == 0.9
    assert seen["url"].endswith("/v1/score/Qwen/Qwen3-Reranker-4B")
    assert seen["body"]["query"] == {"text": "Novato breakfast"} and len(seen["body"]["items"]) == 2


def test_sie_rerank_keeps_order_on_error(monkeypatch):
    from services.memory import sie
    monkeypatch.setenv("SIE_API_KEY", "test")
    out, name = sie.rerank("q", FACTS, client=_sie_client(lambda req: __import__("httpx").Response(500)))
    assert name == "none" and out == FACTS


def test_sie_rerank_without_key(monkeypatch):
    from services.memory import sie
    monkeypatch.setenv("SIE_API_KEY", "")
    assert sie.rerank("q", FACTS) == (FACTS, "none")


def test_recall_reports_reranker(monkeypatch):
    from services.memory import sie
    monkeypatch.setattr(core, "_prepare", lambda: "fallback")
    monkeypatch.setattr(core, "load_index", lambda: FACTS)
    monkeypatch.setattr(sie, "rerank", lambda q, facts: (list(reversed([{**f, "sie_score": 0.5} for f in facts])), "superlinked-sie"))
    out = core.recall("Novato Dublin hotel breakfast", top=5)
    assert out["reranker"] == "superlinked-sie" and len(out["facts"]) == 2
    assert all("sie_score" in f for f in out["facts"])
