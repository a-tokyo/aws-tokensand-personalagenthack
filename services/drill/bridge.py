"""jsonl-process bridge for Firedrill: one JSON request per line on stdin."""
import json
import sys

from services.drill.agent import respond


def serve(stdin=sys.stdin, stdout=sys.stdout):
    print("READY", flush=True)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        req = {}
        try:
            req = json.loads(line)
            out = {"id": req["id"], "output": respond(req.get("input") or "", req.get("session"))}
        except Exception as e:  # report, never retry
            out = {"id": req.get("id"), "error": f"{type(e).__name__}: {e}"[:300]}
        stdout.write(json.dumps(out) + "\n")
        stdout.flush()


if __name__ == "__main__":
    serve()
