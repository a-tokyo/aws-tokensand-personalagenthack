#!/usr/bin/env bash
# Switch Marco to proactive room mode: he sees every message in the trip channels as a quiet
# room event, stays silent, and jumps in only on a trip change. One gateway restart.
#   scripts/marco-proactive-on.sh          apply the config and restart the gateway
#   scripts/marco-proactive-on.sh --no-restart
# Undo: git checkout agent/openclaw agent/workspace/AGENTS.md, then restart.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import json, re
p = "agent/openclaw/_config/slack.json5"
s = open(p).read()
for ch in ("C0CKA55HJ31", "C0CLLEH6D1N"):
    i = s.index(f'"{ch}": {{'); j = s.index("}", i)
    block = s[i:j].replace('"requireMention": true', '"requireMention": false') \
                  .replace('"requireMentionInBotThreads": true', '"requireMentionInBotThreads": false')
    s = s[:i] + block + s[j:]
open(p, "w").write(s)
p = "agent/openclaw/openclaw.json"
d = json.load(open(p))
d["messages"] = {"ackReactionScope": "group-mentions",
                 "groupChat": {"unmentionedInbound": "room_event", "visibleReplies": "message_tool", "historyLimit": 50}}
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
PY
cp agent/openclaw/staged/AGENTS.proactive.md agent/workspace/AGENTS.md
scripts/marco-up.sh openclaw config validate 2>&1 | grep -E "valid|invalid"
[[ "${1:-}" == "--no-restart" ]] && exit 0
PID="$(lsof -nP -t -iTCP:19789 -sTCP:LISTEN || true)"
if [[ -n "$PID" ]]; then kill "$PID"; for _ in $(seq 1 15); do lsof -nP -iTCP:19789 -sTCP:LISTEN >/dev/null || break; sleep 1; done; fi
for _ in 1 2; do
  nohup scripts/marco-up.sh > data/logs/gateway.log 2>&1 &
  for _ in $(seq 1 45); do grep -qE "socket mode connected|refusing" data/logs/gateway.log && break; sleep 2; done
  grep -q "socket mode connected" data/logs/gateway.log && { echo "proactive mode on, Slack connected"; exit 0; }
  sleep 3
done
echo "gateway did not connect; see data/logs/gateway.log" >&2; exit 1
