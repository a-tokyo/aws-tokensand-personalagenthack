# Contracts

All lanes meet here. Do not change a contract without telling the orchestrator.

## Runtime

- Python 3.12 via `uv`. One `pyproject.toml` at the repo root. Each lane adds its own deps.
- Each service has a CLI: `uv run python -m services.<name> <command> [--json '<payload>']`.
- Every CLI prints **one JSON object** to stdout. Errors: exit code 1 and `{"error": "<code>", "detail": "<text>"}`.
- Config comes from env vars (see `.env.example`). Load them with `python-dotenv` from the repo-root `.env`.
- OpenClaw skills in `agent/workspace/.agents/skills/<name>/SKILL.md` call these CLIs with `exec`.

## Audit row (`services/audit`)

One row per agent step. SingleStore table `decisions`. Local fallback: append to `data/audit.jsonl`.

```json
{
  "id": "uuid4",
  "ts": "ISO-8601 UTC",
  "trip_id": "slug, e.g. novato-2026-11-30",
  "act": "book | replan | brief | other",
  "step": "recall | policy | rank | perk_fill | perk_submit | perk_cancel | uber_schedule | uber_cancel | calendar | email_draft | ticket | kb_write | notify | approval",
  "status": "proposed | approved | done | failed | cancelled",
  "summary": "one STE sentence, max 200 chars",
  "sources": [{"type": "cognee | kb | senso | gmail | slack | calendar | perk | web | persona", "ref": "id or url", "quote": "max 200 chars"}],
  "model": "provider/model or null",
  "cost_usd": 0.0,
  "external_ref": "perk trip id, uber ride id, calendar event id, clickup task id, or null",
  "supersedes": "audit row id or null",
  "approved_by": "slack member id or null"
}
```

CLI: `python -m services.audit record --json '<row without id/ts>'` returns `{"id": ...}`.
`python -m services.audit list --trip <trip_id>` returns `{"rows": [...]}`.
Each `record` also logs a Statsig and an Amplitude event named `marco_<step>_<status>`.

## Memory (`services/memory`)

Seed file: `data/seed_facts.jsonl` (gitignored). One fact per line:

```json
{"fact": "Novato 2K visits: Courtyard Novato Marin/Sonoma, king room, room only.", "topic": "hotel | flight | ground | approval | policy | habit | trip", "place": "Novato", "source_type": "slack | gmail | calendar | drive", "source_ref": "permalink or message id", "date": "YYYY-MM-DD"}
```

- `python -m services.memory seed` loads the seed into Cognee and writes the KB pages.
- `python -m services.memory recall --query "<text>"` returns `{"facts": [{"fact", "source_ref", "score", "sie_score"}], "reranker": "superlinked-sie" | "none"}`. SIE (`Qwen/Qwen3-Reranker-4B`) reranks the candidates. Without `SIE_API_KEY`, or on error, the order stays and `reranker` is `none`.
- `python -m services.memory remember --json '<fact>'` adds one fact.
- `python -m services.memory graph --out web/memory-graph.html` writes the Cognee graph.

## Policy (`services/policy`)

`python -m services.policy ask --query "<text>"` returns `{"answer", "citations": [{"ref", "quote"}]}` (Senso).

## Router (`services/router`)

`python -m services.router rank --json '{"task": "...", "options": [...], "facts": [...]}'` returns
`{"choice", "reason", "model", "cost_usd", "tier": "small | large"}`.

## Perk (`services/perk`)

- `plan --json '{"trip_id","origin","destination","depart","return","hotel","breakfast","description"}'` returns `{"status": "ready_for_approval", "screenshot", "summary"}`. It stops before "Request Approval".
- `submit --trip <trip_id>` presses "Request Approval" only if env `PERK_ALLOW_SUBMIT=1`. Returns `{"perk_trip_id"}`.
- `cancel --perk-trip <id>` returns `{"status"}`.
- Every description must start with: `HACKATHON TEST, DO NOT APPROVE.`

## Uber (`services/uber`)

- `schedule --json '{"pickup","dropoff","when_iso","expense_code"}'` returns `{"ride_id", "status"}`.
- `cancel --ride <id>` returns `{"status", "fee"}`.

## gws actions (`services/gws`)

- `calendar-block --json '{"trip_id","start","end","title"}'` returns `{"event_ids": [...]}`.
- `calendar-move --json '{"event_ids","start","end"}'`.
- `draft-email --json '{"to","subject","body"}'` returns `{"draft_id"}`. It drafts only and never sends.
- `ticket --json '{"title","due","description"}'` returns `{"task_id"}` (ClickUp).
- `watch-gmail --since <iso>` returns `{"changes": [{"message_id","subject","old_dates","new_dates","trip_id"}]}`.
- `replan --trip <trip_id> --json '<change>'` returns `{"proposal": "STE text", "actions": [...]}`, built from the audit rows.

## Env keys (names only, values in `.env`)

See `.env.example`.
