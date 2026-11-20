---
name: gws-actions
description: Act on Tokyo's Google Workspace and ClickUp: block or move calendar time, draft an email, open a ticket, watch Gmail for trip changes. Use it after a trip plan is approved.
metadata: { "openclaw": { "requires": { "bins": ["uv"] } } }
---

# gws-actions

Stub. Another lane writes the CLI. Run every command from the repo root with `uv run python -m`. Each command prints one JSON object. The full contract is `docs/contracts.md`.

**Approval gate.** Never run a write step until Tokyo replies "approve" from his own member id, as listed in `USER.md`. A name match is not enough. First record the step as `proposed`, then record it as `approved` with `approved_by` set to that id.

## Commands

- `uv run python -m services.gws calendar-block --json '{"trip_id","start","end","title"}'` returns `{"event_ids"}`.
- `uv run python -m services.gws calendar-move --json '{"event_ids","start","end"}'`.
- `uv run python -m services.gws draft-email --json '{"to","subject","body"}'` returns `{"draft_id"}`. It drafts only. It never sends.
- `uv run python -m services.gws ticket --json '{"title","due","description"}'` returns `{"task_id"}`.
- `uv run python -m services.gws watch-gmail --since <iso>` returns `{"changes": [...]}`.

## Rules

- Calendar writes and tickets are write steps. The approval gate applies.
- Never send an email. Draft only. Never address a draft to a real person for a test.
- Audit steps: `calendar`, `email_draft`, `ticket`.

After each step, write one audit row with the `audit-trail` skill.
