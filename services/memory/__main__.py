"""Marco memory CLI: seed, recall, remember, graph, kb-append."""
import argparse
import json
import sys

from . import core, kb


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="services.memory")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    r = sub.add_parser("recall")
    r.add_argument("--query", required=True)
    r.add_argument("--top", type=int, default=5)
    m = sub.add_parser("remember")
    m.add_argument("--json", required=True)
    g = sub.add_parser("graph")
    g.add_argument("--out", default="web/memory-graph.html")
    g.add_argument("--local", action="store_true", help="skip Cognee, draw the local graph")
    k = sub.add_parser("kb-append")
    k.add_argument("--json", required=True)
    a = p.parse_args(argv)
    if a.cmd == "seed":
        out = core.seed()
    elif a.cmd == "recall":
        out = core.recall(a.query, a.top)
    elif a.cmd == "remember":
        out = core.remember(json.loads(a.json))
    elif a.cmd == "graph":
        out = core.graph(a.out, a.local)
    else:
        out = kb.kb_write(json.loads(a.json))
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
