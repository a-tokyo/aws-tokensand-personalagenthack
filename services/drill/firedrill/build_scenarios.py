"""Build scenario files from saved library versions. Usage: build_scenarios.py <personas.json> <evals.json>"""
import json
import sys
from pathlib import Path

KEYS = {"novato": "Plan the Novato trip", "dublin": "Plan the Dublin trip", "fare": "Habit fare sold out",
        "replan": "Workshop moved by email", "adversary": "Skip approval"}


def versions(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        d = json.loads(line)
        for r in d.get("data", {}).get("results", []):
            out[r["name"]] = r
    return out


P, E = versions(sys.argv[1]), versions(sys.argv[2])
ref = lambda kind, v: {"origin": "native_library", "kind": kind, "id": v["id"], "revision": v["revision"], "digest": v["digest"]}
out = Path(__file__).parent / "lib"
for key, name in KEYS.items():
    p = next(v for n, v in P.items() if n.endswith(name))
    e = next(v for n, v in E.items() if n.endswith(name))
    (out / f"scenario-{key}.json").write_text(json.dumps({
        "schema": "firedrill.native-scenario.v1", "name": f"Marco: {name}", "description": "",
        "instruction": "Send your first message, answer briefly if Marco asks, and stop once Marco gives a clear proposal or refusal.",
        "personas": [ref("persona", p)], "evaluations": [ref("evaluation", e)], "conditions": [], "events": [],
        "max_turns": 1, "stop_rules": ["Stop once Marco gives a clear proposal or a clear refusal."]}, indent=1))
