"""Self-contained force graph of Marco's memory (vis-network). Built from the index and kb wikilinks."""
import json
import re
from pathlib import Path

from . import core, kb

GROUPS = {
    "traveller": ("#ffb454", "dot", 34), "place": ("#4fd1c5", "dot", 26), "hotel": ("#f6ad55", "box", 16),
    "trip": ("#63b3ed", "diamond", 20), "preference": ("#b794f4", "ellipse", 14),
    "approval": ("#fc8181", "star", 24), "airline": ("#68d391", "triangle", 18),
}
AIRLINES = {"TAP": r"\bTAP\b|TP\d+", "Ryanair": r"Ryanair|FR\d+"}
LINK = re.compile(r"\[\[(?:wiki/)?([^\]|]+)\]\]")


def build() -> dict:
    nodes, edges, ids = [], set(), {}
    root = kb.KB / "wiki"
    for p in sorted(root.glob("*/*.md")):
        typ = p.parent.name.rstrip("s") if p.parent.name != "approval" else "approval"
        typ = {"traveller": "traveller", "place": "place", "hotel": "hotel", "trip": "trip", "preference": "preference"}.get(typ, typ)
        t = re.search(r"title: (.*)", p.read_text()).group(1)
        key = f"{p.parent.name}/{p.stem}"
        ids[key] = len(ids) + 1
        nodes.append((key, t, typ, re.sub(r"^---.*?---\s*", "", p.read_text(), flags=re.S)[:300]))
    for key, *_ in nodes:
        text = (root / f"{key}.md").read_text()
        for tgt in LINK.findall(text):
            tgt = tgt.removeprefix("wiki/")
            if tgt in ids and tgt != key:
                edges.add(tuple(sorted((ids[key], ids[tgt]))))
    out = []
    for key, t, typ, tip in nodes:
        c, shape, size = GROUPS.get(typ, GROUPS["preference"])
        out.append({"id": ids[key], "label": t, "shape": shape, "size": size, "color": c,
                    "title": tip.replace("\n", "<br>"), "font": {"color": "#e6edf3", "size": 14 if size > 20 else 11}})
    facts = core.load_index() or (core._read_seed() if core.SEED.exists() else [])
    for name, rx in AIRLINES.items():
        hit = [f for f in facts if re.search(rx, f["fact"])]
        if not hit:
            continue
        nid = len(ids) + 1
        ids[f"airline/{name}"] = nid
        c, shape, size = GROUPS["airline"]
        out.append({"id": nid, "label": name, "shape": shape, "size": size, "color": c,
                    "title": f"{len(hit)} facts", "font": {"color": "#e6edf3", "size": 13}})
        for f in hit:
            for key in ids:
                if key.startswith("places/") and f.get("place", "").lower().replace(" ", "-") == key.split("/")[1]:
                    edges.add(tuple(sorted((nid, ids[key]))))
    return {"nodes": out, "edges": [{"from": a, "to": b} for a, b in sorted(edges)]}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Marco memory</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.9/standalone/umd/vis-network.min.js"></script>
<style>html,body{margin:0;height:100%;background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif}
#g{position:absolute;inset:0}h1{position:absolute;left:24px;top:16px;margin:0;font-size:28px;z-index:2;letter-spacing:.5px}
h1 small{display:block;font-size:13px;font-weight:400;color:#8b949e;margin-top:4px}
.leg{position:absolute;left:24px;bottom:20px;z-index:2;font-size:12px;color:#8b949e}.leg i{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 6px 0 12px}</style></head>
<body><h1>Marco memory<small>What Marco knows about Tokyo's travel. Facts only.</small></h1><div id="g"></div>
<div class="leg">__LEG__</div>
<script>var d=__DATA__;new vis.Network(document.getElementById('g'),{nodes:new vis.DataSet(d.nodes),edges:new vis.DataSet(d.edges)},
{physics:{solver:'forceAtlas2Based',forceAtlas2Based:{gravitationalConstant:-70,springLength:110},stabilization:{iterations:250}},
edges:{color:{color:'#30363d',highlight:'#58a6ff'},smooth:{type:'continuous'},width:1.2},interaction:{hover:true,tooltipDelay:100}});</script></body></html>"""


def write(path: Path):
    leg = "".join(f'<i style="background:{c}"></i>{n}' for n, (c, _, _) in GROUPS.items())
    path.write_text(PAGE.replace("__DATA__", json.dumps(build())).replace("__LEG__", leg))
