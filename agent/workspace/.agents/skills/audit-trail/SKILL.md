---
name: audit-trail
description: Write and read Marco's audit trail. Use it after every step you take, and when Tokyo asks what Marco did or why.
metadata: { "openclaw": { "requires": { "bins": ["uv"] } } }
---

# audit-trail

Stub. Another lane writes the CLI. Run every command from the repo root with `uv run python -m`. Each command prints one JSON object. The full contract is `docs/contracts.md`.

**Approval gate.** Never run a write step until Tokyo replies "approve" from his own member id, as listed in `USER.md`. A name match is not enough. First record the step as `proposed`, then record it as `approved` with `approved_by` set to that id.

## Commands

- Record: `uv run python -m services.audit record --json '<row>'` returns `{"id"}`. Leave out `id` and `ts`.
- List: `uv run python -m services.audit list --trip <trip_id>` returns `{"rows": [...]}`.

## Row fields

`trip_id`, `act` (book, replan, brief, other), `step`, `status` (proposed, approved, done, failed, cancelled), `summary` (one STE sentence, max 200 chars), `sources` (`type`, `ref`, `quote`), `model`, `cost_usd`, `external_ref`, `supersedes`, `approved_by`.

## Rules

- One row per step. No step is done until its row exists.
- A changed plan gets a new row with `supersedes` set. Never edit an old row.
- Never put card, passport, plate or reservation numbers in a row.

After each step, write one audit row with the `audit-trail` skill.
