# Marco: a personal chief-of-staff agent with an audit trail

Marco does the travel work that tools like Perk and Navan still leave to people. It remembers your habits, checks the company policy and finds the best value. It books, reschedules and cleans up after you, and it keeps one human click for accountability. Marco does the work; people keep the decision. We enable people, we do not replace them. Every step goes on an audit trail.

Built at the tokens& Personal Agents Hackathon, San Francisco, 2026-11-20, by **Ahmed Tokyo** and **Claudia Freitas**.

We built Marco in one day for this hackathon. Starting today, we use it at our company to run the dull work on every Perk trip.

## The problem

At a consultancy, each client trip is still manual. The traveller or a facilities person asks the same questions every time: who approved it, who pays, where, which hotel, which documents. When plans change, a person has to unwind everything: the flight, the hotel, the calendar, the ride and the people to tell.

## What Marco does

**Act 1: book.** In Slack, Tokyo writes: "@Marco 2K wants me in Novato for Bart's AI workshop, 30 Nov to 2 Dec. Plan the trip."

1. **Recall.** Marco's memory is built from Tokyo's connected tools: Slack threads, Gmail booking emails, Calendar, Drive (travel policy) and the knowledge base. New sources, such as Jira or Telegram, plug in the same way. Marco remembers that Tokyo stays at the Courtyard Novato, room only, and buys breakfast himself. Each memory comes with its source (a Slack thread or a booking email).
2. **Policy.** It checks the company travel policy, for example "breakfast changes the per diem", and cites the passage.
3. **Best value.** Tokyo usually flies TAP at 07:00, but economy is sold out and business is out of policy (€4.7k). Marco ranks the options and offers a choice:
   - **A)** KLM, €1,411, the best value, in policy.
   - **B)** Lufthansa, €1,295, Star Alliance, so Tokyo's TAP miles still earn.
   - **C)** The TAP habit, out of policy.
4. **Prepare.** It fills the Perk trip (cost centre, billable to client, approver note), proposes calendar blocks, and schedules an Uber to the airport on the company profile, with the client name as the expense code (a finance rule it remembered).
5. **Catch problems.** It spots that the return flight leaves before the scheduled Uber, and proposes a fix.
6. **One human click.** Tokyo replies "approve A". Nothing is bought before that.

**Act 2: plans change.** An email arrives: the workshop moves to January. Marco notices it without being asked. It finds every item linked to the trip on the audit trail, and proposes one plan: move the Perk trip, the calendar blocks, the Uber and the expenses ticket, and draft notes to the people involved. One click applies it. The new rows link to the rows they replace.

## Audit trail

Every step writes one row: the step, the decision, the sources, the model, the cost, and the row it supersedes. Rows go to SingleStore, with a local JSONL mirror. `web/audit.html` shows the trail per trip.

## Sponsor tools

| Sponsor | What Marco uses it for |
|---|---|
| **Cognee** | Long-term memory: every past trip, hotel and habit, recalled with its source. Graph view in Cognee Cloud (dataset `marco_memory`). The same memory is a human-readable Obsidian vault in `kb/`. |
| **Senso** | The travel policy as a context layer. Each choice is checked against policy, with a citation. |
| **SingleStore** | The audit trail table `decisions`. |
| **Statsig** | The `auto_submit` gate stays off, so a human approves every purchase. Each step is also an event. |
| **Amplitude** | Agent analytics: each step of each trip is a tracked event. |
| **Superlinked SIE** | Reranks memory recall (Qwen3-Reranker on SIE Serverless), so the right habit comes first. |
| **Firedrill** | Simulated travellers and plan changes test Marco's decisions before they touch real bookings (`services/drill`). |

## How it is built

- **Runtime:** [OpenClaw](https://github.com/openclaw/openclaw) 2026.10.9. The config is adapted from our production agents (Pascal, Marvis), which already run Slack, memory and cost tracking.
- **Channels:** Slack (socket mode; tag @Marco in a trip thread; only Tokyo can approve) and Telegram (DM).
- **Actions:** Perk and Uber through a browser MCP on Tokyo's own logged-in browser. Google Calendar, Gmail drafts and Tasks through the `gws` CLI.
- **Services** (Python, `uv`), one CLI each, defined in `docs/contracts.md`:
  - `services/memory`: Cognee recall and the Obsidian vault in `kb/`.
  - `services/policy`: Senso.
  - `services/router`: option ranking (cheap tier for routine steps, strong tier for ranking) and a per-call cost ledger.
  - `services/audit`: SingleStore, Statsig, Amplitude.
  - `services/gws`: calendar, drafts, tasks, Gmail watcher, replan.
- **Skills:** `agent/workspace/.agents/skills/` holds the perk-booker, uber-schedule, trip-memory, travel-policy, audit-trail, gws-actions and replan recipes.

## Run it

```bash
cp .env.example .env            # fill the keys
uv sync
uv run pytest -q                # unit tests
uv run python -m services.memory seed
scripts/marco-up.sh             # starts the gateway; talk to @Marco in Slack
```

## Safety rules

- Marco never buys, submits, schedules or sends anything without "approve" from its owner.
- Messages to other people are drafts only.
- The demo Perk trip carries "HACKATHON TEST, DO NOT APPROVE" and stays a draft. The demo Uber reservation has free cancellation and is cancelled after the demo.
- Memory, policy and model providers get extracted facts only. Card, passport and reservation numbers are never stored.
