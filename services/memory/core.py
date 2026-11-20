"""Memory backend: Cognee when configured, keyword fallback otherwise.

Each fact is stored as "[src:<ref>] <text>" so recall can cite the source.
A local index (data/memory_index.jsonl) backs the fallback and the citations.
"""
import asyncio
import json
import os
import re
from pathlib import Path

from . import sie

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "data" / "seed_facts.jsonl"
INDEX = ROOT / "data" / "memory_index.jsonl"
DATASET = "marco_memory"
POOL = 3  # candidates per returned fact, so the reranker can promote a low keyword match
TAG = re.compile(r"\[src:([^\]]*)\]\s*")
STOP = {"the", "a", "an", "to", "in", "of", "and", "for", "is", "on", "at", "he", "his", "i", "do", "does", "how", "what", "where", "when", "with"}


def _env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass


def backend() -> str:
    """Return 'cloud', 'local' or 'fallback' from env keys."""
    _env()
    if os.getenv("COGNEE_URL") and os.getenv("COGNEE_API_KEY"):
        return "cloud"
    if os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"):
        return "local"
    return "fallback"


def _prepare():
    """Set env for Cognee. Return the backend name."""
    b = backend()
    if b == "local":
        key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        os.environ.setdefault("LLM_API_KEY", key)
        os.environ.setdefault("EMBEDDING_API_KEY", os.getenv("OPENAI_API_KEY") or key)
        os.environ.setdefault("COGNEE_SKIP_CONNECTION_TEST", "true")
        os.environ.setdefault("ENABLE_BACKEND_ACCESS_CONTROL", "false")
    return b


async def _connect(b):
    import cognee
    if b == "cloud":
        await _maybe(cognee.serve(url=os.environ["COGNEE_URL"], api_key=os.environ["COGNEE_API_KEY"]))
    return cognee


async def _maybe(x):
    return await x if asyncio.iscoroutine(x) or hasattr(x, "__await__") else x


def tagged(f: dict) -> str:
    return f"[src:{f.get('source_ref', '')}] {f['fact']}"


def load_index() -> list[dict]:
    if not INDEX.exists():
        return []
    return [json.loads(x) for x in INDEX.read_text().splitlines() if x.strip()]


def _write_index(facts: list[dict]):
    INDEX.parent.mkdir(exist_ok=True)
    INDEX.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in facts))


def _read_seed() -> list[dict]:
    return [json.loads(x) for x in SEED.read_text().splitlines() if x.strip()]


def _merge(facts: list[dict], new: list[dict]) -> list[dict]:
    seen = {f["fact"] for f in facts}
    return facts + [f for f in new if f["fact"] not in seen]


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP}


def fallback_recall(query: str, top: int = 5, facts: list[dict] | None = None) -> dict:
    facts = load_index() if facts is None else facts
    if not facts and SEED.exists():
        facts = _read_seed()
    q = _tokens(query)
    scored = []
    for f in facts:
        hay = _tokens(" ".join([f["fact"], f.get("topic", ""), f.get("place", "")]))
        s = len(q & hay) / (len(q) or 1)
        if s > 0:
            scored.append({"fact": f["fact"], "source_ref": f.get("source_ref", ""), "score": round(s, 3)})
    scored.sort(key=lambda x: -x["score"])
    return {"facts": scored[:top], "backend": "fallback"}


async def _cognee_store(b: str, texts: list[str]):
    cognee = await _connect(b)
    await _maybe(cognee.remember(texts, dataset_name=DATASET))


def seed() -> dict:
    from . import kb
    facts = _read_seed()
    _write_index(_merge(load_index(), facts))
    kb_res = kb.build_vault(facts)
    b = _prepare()
    res = {"facts": len(facts), "backend": "fallback", "kb": kb_res}
    if b != "fallback":
        try:
            asyncio.run(_cognee_store(b, [tagged(f) for f in facts]))
            res["backend"] = b
        except Exception as e:
            res["cognee_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return res


def remember(fact: dict) -> dict:
    fact = {"topic": "", "place": "", "source_type": "agent", "source_ref": "", "date": "", **fact}
    _write_index(_merge(load_index(), [fact]))
    b = _prepare()
    res = {"stored": True, "backend": "fallback"}
    if b != "fallback":
        try:
            asyncio.run(_cognee_store(b, [tagged(fact)]))
            res["backend"] = b
        except Exception as e:
            res["cognee_error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return res


def _entry_text(r) -> str:
    """Pull the answer text out of a Cognee entry (object, dict or string)."""
    if isinstance(r, str):
        return r
    d = r if isinstance(r, dict) else getattr(r, "__dict__", {})
    if d.get("status") or "memory_warming_up" in str(r):
        return ""
    for k in ("text", "answer", "content"):
        if d.get(k):
            return str(d[k])
    raw = d.get("raw")
    if isinstance(raw, dict) and raw.get("value"):
        return str(raw["value"])
    return "" if d else str(r)


def _cite(text: str, index: list[dict]) -> str:
    """Best source_ref for a Cognee answer: the index fact with most word overlap."""
    t = _tokens(text)
    best, ref = 0.0, ""
    for f in index:
        h = _tokens(f["fact"])
        s = len(t & h) / (len(h) or 1)
        if s > best:
            best, ref = s, f.get("source_ref", "")
    return ref if best >= 0.4 else ""


def _parse(results, index: list[dict]) -> list[dict]:
    """Turn Cognee results into facts with sources. Cite via the [src:] tag or the index."""
    by_text = {f["fact"]: f for f in index}
    out, seen = [], set()
    for i, r in enumerate(results or []):
        text = _entry_text(r)
        for chunk in re.split(r"(?=\[src:)", text):
            chunk = chunk.strip()
            if not chunk:
                continue
            m = TAG.match(chunk)
            ref, fact = (m.group(1), chunk[m.end():]) if m else ("", chunk)
            fact = fact.strip()
            if not ref:
                ref = by_text[fact].get("source_ref", "") if fact in by_text else _cite(fact, index)
            if fact and fact not in seen:
                seen.add(fact)
                out.append({"fact": fact, "source_ref": ref, "score": round(1 - i * 0.05, 3)})
    return out


async def _cognee_recall(b: str, query: str, top: int):
    cognee = await _connect(b)
    return await _maybe(cognee.recall(query, datasets=[DATASET], top_k=top))


def recall(query: str, top: int = 5) -> dict:
    """Cognee answers first, keyword fallback fills the pool, SIE reranks. Real cited facts always return."""
    b = _prepare()
    index = load_index() or (_read_seed() if SEED.exists() else [])
    cog = []
    if b != "fallback":
        try:
            cog = _parse(asyncio.run(_cognee_recall(b, query, top)), index)
        except Exception:
            cog = []
    fb = fallback_recall(query, top * POOL, facts=index)["facts"]
    seen = {f["fact"] for f in cog}
    merged, reranker = sie.rerank(query, cog + [f for f in fb if f["fact"] not in seen])
    out = {"facts": merged[:top], "reranker": reranker}
    if b == "fallback":
        return {**out, "backend": "fallback"}
    return {**out, "backend": "cloud" if b == "cloud" and cog and not fb else f"{b}+fallback"}


def _cloud_graph(path: Path) -> str:
    import httpx
    h = {"X-Api-Key": os.environ["COGNEE_API_KEY"]}
    if os.getenv("COGNEE_TENANT_ID"):
        h["X-Tenant-Id"] = os.environ["COGNEE_TENANT_ID"]
    base = os.environ["COGNEE_URL"].rstrip("/") + "/api/v1"
    with httpx.Client(headers=h, timeout=90, follow_redirects=True) as c:
        ds = c.get(f"{base}/datasets").raise_for_status().json()
        ids = [d["id"] for d in ds if d["name"] == DATASET]
        if not ids:
            raise RuntimeError("dataset not found")
        r = c.get(f"{base}/visualize", params={"dataset_id": ids[0]}).raise_for_status()
        if len(r.text) < 2000:
            raise RuntimeError("empty graph")
        path.write_text(r.text)
    return "cloud"


def graph(out: str, local: bool = False) -> dict:
    """Cloud: fetch HTML from the HTTP API. Else local Cognee. Else a self-made force graph."""
    from . import graphviz
    b = _prepare()
    path = Path(out) if Path(out).is_absolute() else ROOT / out
    path.parent.mkdir(parents=True, exist_ok=True)
    err = None
    if b == "cloud" and not local:
        try:
            return {"path": str(path), "backend": _cloud_graph(path)}
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:150]}"
    elif b == "local" and not local:
        async def go():
            cognee = await _connect(b)
            return await _maybe(cognee.visualize_graph(str(path), dataset=DATASET))
        try:
            asyncio.run(go())
            return {"path": str(path), "backend": b}
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:150]}"
    graphviz.write(path)
    res = {"path": str(path), "backend": "fallback"}
    if err:
        res["cognee_error"] = err
    return res
