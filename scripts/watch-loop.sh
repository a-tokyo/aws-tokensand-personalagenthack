#!/usr/bin/env bash
# Poll Gmail every 60s. On a workshop date change, print the replan proposal JSON.
# Run from the repo root. Does not execute any action.
cd "$(dirname "$0")/.." || exit 1
SINCE="${1:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
while true; do
  NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  OUT="$(uv run python -m services.gws watch-gmail --since "$SINCE")"
  echo "$OUT" | python3 -c '
import json,sys
for c in json.load(sys.stdin).get("changes", []):
    print(json.dumps(c))' | while read -r CHANGE; do
    TRIP="$(echo "$CHANGE" | python3 -c 'import json,sys;print(json.load(sys.stdin)["trip_id"])')"
    uv run python -m services.gws replan --trip "$TRIP" --json "$CHANGE"
  done
  SINCE="$NOW"
  sleep 60
done
