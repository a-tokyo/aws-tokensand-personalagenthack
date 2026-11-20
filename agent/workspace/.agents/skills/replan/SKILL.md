---
name: replan
description: Propose a new plan when a trip changes, for example a moved meeting or a changed flight. Use it when `watch-gmail` reports a change, or when Tokyo says a date moved.
metadata: { "openclaw": { "requires": { "bins": ["uv"] } } }
---

# replan

Stub. Another lane writes the CLI. Run every command from the repo root with `uv run python -m`. Each command prints one JSON object. The full contract is `docs/contracts.md`.

**Approval gate.** Never run a write step until Tokyo replies "approve" from his own member id, as listed in `USER.md`. A name match is not enough. First record the step as `proposed`, then record it as `approved` with `approved_by` set to that id.

## Command

`uv run python -m services.gws replan --trip <trip_id> --json '<change>'` returns `{"proposal","actions"}`. It reads the audit rows for the trip.

## Rules

- Send Tokyo the proposal. Run no action until he approves.
- Each new row sets `supersedes` to the row it replaces.
- Audit act: `replan`.

After each step, write one audit row with the `audit-trail` skill.
