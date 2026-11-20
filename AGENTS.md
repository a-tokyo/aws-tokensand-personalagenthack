# AGENTS.md: Marco

Marco is Tokyo's personal chief-of-staff agent. It runs on OpenClaw, which we copied from Pascal.
The workspace contract at `../AGENTS.md` applies here too. This file adds project rules.

## Read first

1. `docs/contracts.md`: CLI shapes, the audit row and env keys. Every lane meets the others there.
2. `/Users/admin.ahmed.tokyo/.claude/plans/pasted-content-id-0f60-we-are-fluttering-dove.md`: the plan (local only).

## Layout

| Path | Owner lane | Content |
|---|---|---|
| `agent/openclaw/` | L1 harness | OpenClaw config (`openclaw.json`, `_config/`) |
| `agent/workspace/` | L1 harness | Marco's `SOUL.md`, `IDENTITY.md`, `USER.md`, `AGENTS.md`, skills |
| `services/audit/` | L6 | Audit writer (SingleStore + JSONL fallback), Statsig and Amplitude events |
| `services/memory/` | L5 | Cognee seed, recall, graph |
| `services/router/` | L7 | Arcee Pareto router, cost ledger |
| `services/policy/` | L9 | Senso policy client |
| `services/gws/` | L8 | Calendar, drafts, ClickUp, Gmail watcher, replan |
| `services/perk/` | L2 | Perk browser automation |
| `services/uber/` | L3 | Uber browser automation |
| `kb/` | L5 | Obsidian vault (demo-safe content only) |
| `web/` | L6 | `audit.html` and the memory graph |
| `data/` | all | Gitignored runtime data and seed facts |

## Rules

- Edit only your lane's folder. Only the orchestrator edits `openclaw.json`, `AGENTS.md`, `.env.example` and `pyproject.toml` deps (ask for a dep in your report, or add it with `uv add` if you own a whole lane).
- Never print secrets. Read config from env only.
- Tests go in `tests/test_<service>.py`. Test logic, not config. Run them with `uv run pytest -q`.
- Every external action writes an audit row first as `proposed`, then as `done` or `failed`.
