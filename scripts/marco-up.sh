#!/usr/bin/env bash
# Start Marco's OpenClaw gateway natively, with state fully separate from any other agent.
#
#   scripts/marco-up.sh                  start the gateway in the foreground
#   scripts/marco-up.sh openclaw <args>  run any openclaw command in Marco's env
#   scripts/marco-up.sh chat "<text>"    run one local agent turn (no channels needed)
#
# It never prints secret values.
#
# Config notes (OpenClaw rewrites agent/openclaw/openclaw.json and strips its comments, so they live here):
# - plugins.deny ["codex"] stays. The Codex ACP harness swallowed message and tool flow in Pascal.
#   A deny survives `doctor --fix`; `enabled: false` does not. `doctor --fix` rewrites config: diff after it.
# - Allowlists use ${SLACK_OWNER_ID} and ${TELEGRAM_OWNER_ID}. An unset id stays literal and denies silently.
# - Slack channel allowlist keys are channel IDS (C...), never names. _config edits need a restart.
# - The Slack plugin is not bundled: `scripts/marco-up.sh openclaw plugins install @openclaw/slack@2026.10.9`.
# - Port 19789 and loopback bind keep Marco clear of any other local gateway.
set -euo pipefail

MARCO_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MARCO_HOME

# OpenClaw 2026.10.9 needs Node >=24.22.1. Pin the nvm build, not the shell default.
NODE_BIN="${MARCO_NODE_BIN:-$HOME/.nvm/versions/node/v24.22.3/bin}"
if [[ ! -x "$NODE_BIN/openclaw" ]]; then
  echo "openclaw not found in $NODE_BIN. Run: nvm install 24 && npm i -g openclaw@2026.10.9" >&2
  exit 1
fi
export PATH="$NODE_BIN:$PATH"

MARCO_KEYS=(ANTHROPIC_API_KEY GATEWAY_AUTH_TOKEN SLACK_BOT_TOKEN SLACK_APP_TOKEN SLACK_OWNER_ID
            TELEGRAM_BOT_TOKEN TELEGRAM_OWNER_ID OPENAI_API_KEY
            OPENROUTER_API_KEY OPENCLAW_GATEWAY_TOKEN)
# Drop inherited values, so Marco runs on the repo .env only and never on another agent's key.
unset "${MARCO_KEYS[@]}"

# Export the repo .env into the process env. OpenClaw ignores provider keys from a cwd .env,
# so the process env is the only layer that reaches the gateway.
if [[ -f "$MARCO_HOME/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$MARCO_HOME/.env"
  set +a
else
  echo "warning: $MARCO_HOME/.env is missing. Copy .env.example and fill it." >&2
fi

# Dedicated state, config and workspace. Never ~/.openclaw.
export OPENCLAW_STATE_DIR="$MARCO_HOME/.openclaw-state"
export OPENCLAW_CONFIG_PATH="$MARCO_HOME/agent/openclaw/openclaw.json"
export OPENCLAW_WORKSPACE_DIR="$MARCO_HOME/agent/workspace"
mkdir -p "$OPENCLAW_STATE_DIR"
chmod 700 "$OPENCLAW_STATE_DIR"

# Report which keys are set. Names only.
for k in "${MARCO_KEYS[@]}"; do
  if [[ -n "${!k:-}" ]]; then echo "  set:   $k" >&2; else echo "  unset: $k" >&2; fi
done

cd "$MARCO_HOME"
case "${1:-}" in
  openclaw) shift; exec openclaw "$@" ;;
  chat)     shift; exec openclaw agent --local --agent main --session-id "marco-cli" -m "$*" ;;
  "")       exec openclaw gateway run ;;
  *)        echo "usage: $0 [openclaw <args> | chat <text>]" >&2; exit 2 ;;
esac
