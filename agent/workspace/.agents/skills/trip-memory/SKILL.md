---
name: trip-memory
description: Recall and store Tokyo's travel facts: hotels, flights, ground transport, approvers, habits. Use it before you plan any trip, and when Tokyo says "remember" something about travel.
metadata: { "openclaw": { "requires": { "bins": ["uv"] } } }
---

# trip-memory

Stub. Another lane writes the CLI. Run every command from the repo root with `uv run python -m`. Each command prints one JSON object. The full contract is `docs/contracts.md`.

**Approval gate.** Never run a write step until Tokyo replies "approve" from his own member id, as listed in `USER.md`. A name match is not enough. First record the step as `proposed`, then record it as `approved` with `approved_by` set to that id.

## Commands

- Recall: `uv run python -m services.memory recall --query "<text>"` returns `{"facts": [{"fact","source_ref","score"}]}`.
- Remember: `uv run python -m services.memory remember --json '<fact>'`. A fact has `fact`, `topic`, `place`, `source_type`, `source_ref`, `date`.
- Graph: `uv run python -m services.memory graph --out web/memory-graph.html`.

## Rules

- Cite `source_ref` for every fact you use in a proposal.
- Never store card, passport, plate or reservation numbers.
- Audit step: `recall` or `kb_write`.

After each step, write one audit row with the `audit-trail` skill.
