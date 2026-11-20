---
name: travel-policy
description: Check a trip against Mindera's travel policy. Use it before you propose a hotel, flight or ride, and when Tokyo asks what the policy allows.
metadata: { "openclaw": { "requires": { "bins": ["uv"] } } }
---

# travel-policy

Stub. Another lane writes the CLI. Run every command from the repo root with `uv run python -m`. Each command prints one JSON object. The full contract is `docs/contracts.md`.

**Approval gate.** Never run a write step until Tokyo replies "approve" from his own member id, as listed in `USER.md`. A name match is not enough. First record the step as `proposed`, then record it as `approved` with `approved_by` set to that id.

## Command

`uv run python -m services.policy ask --query "<text>"` returns `{"answer","citations": [{"ref","quote"}]}`.

## Rules

- Quote the citation in the proposal. Do not paraphrase a limit from memory.
- If the policy has no answer, say so. Do not guess.
- Audit step: `policy`.

After each step, write one audit row with the `audit-trail` skill.
