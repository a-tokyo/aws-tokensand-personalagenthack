# Live demo runbook (2 minutes)

Channel: `#novato-trip` (`C0CLLEH6D1N`). Tokyo types every message from his own Slack account.
The trip is `data/trip_novato.json` (`novato-live-demo-2026-11`, `"demo_mode": true`).
In demo mode, Perk and Uber are "prepared, held". Marco makes no browser call. Nothing is bought.
Calendar events and the expenses task are real. Delete them after the demo (see "After").

## Before (T-5 min)

```bash
scripts/marco-up.sh openclaw channels status     # Slack + Telegram: connected
uv run python -m services.audit gate --name auto_submit     # {"enabled": false}
uv run python -m services.audit gate --name proactive_mode  # {"enabled": true}
uv run python scripts/marco_ops.py room-check --text "Bart's Novato workshop moved to Jan 12-14"  # act: true
```

Open these tabs: Slack `#novato-trip`, `web/audit.html` (run `scripts/audit-standalone.sh` first),
`web/memory-graph-cloud.html` (Cognee graph), https://app.guild.ai/users/a-tokyo/agents/a-tokyo~marco-trip-desk.

## Beats

| # | Type in `#novato-trip` (new top-level message unless noted) | Expect | Target |
|---|---|---|---|
| 1 | `@Marco 2K wants me in Novato for Bart's AI workshop, 30 Nov to 2 Dec. Plan the trip.` | `On it.`, then the itinerary card with options A/B/C, policy and `Reply "@Marco approve A"`. | rehearsal 15:50 PT: ack 10 s, card 83 s. Talk over the wait (memory, policy). |
| 2 | In the same thread: `@Marco approve A` | `On it.` (7 s). Marco **edits the card above in place** to "Done. Calendar and task are set. Perk and Uber are prepared, held for live demo." Scroll up to show it. | rehearsal: < 90 s |
| 3 | New message, **no tag**: `fyi Bart's Novato workshop moved to Jan 12-14` | Marco jumps in once, with the replan card (calendar, task, Perk, Uber, 2 drafts). Do **not** approve it. | rehearsal: 15 s |
| 4 | `@Marco can I also do the Lisbon client offsite, 1 to 3 Dec?` | Clash card: overlaps Novato 30 Nov to 4 Dec. Options: send someone else, shift dates, cut short. | rehearsal: ack 9 s, card 16 s |
| 5 | Show `web/audit.html` (trip `novato-live-demo-2026-11`), the Cognee graph, then Guild: ask "Does hotel breakfast change my per diem?" | One row per step, with sources. | 30 s |

Optional beat (only if time): in a new message, `Ana will go to Novato instead of Tokyo.` Marco posts
the cancel card. Do **not** approve it.

## Fallback if Slack is slow (> 60 s)

Run the same step from the terminal. Each command posts the same card to the thread:

```bash
TS=<thread ts>   # from "Copy link" on the message
uv run python scripts/marco_itinerary.py --channel C0CLLEH6D1N --thread-ts $TS --mention <Tokyo id> --status 'Reply "@Marco approve A".'
uv run python scripts/marco_approve.py --trip novato-live-demo-2026-11 --option A --approved-by <Tokyo id> --thread-ts $TS
uv run python scripts/marco_itinerary.py --channel C0CLLEH6D1N --thread-ts $TS --mention <Tokyo id> --status "Done. Calendar and task are set. Perk and Uber are prepared, held for live demo."
uv run python scripts/marco_ops.py replan-text --text "fyi Bart's Novato workshop moved to Jan 12-14" --thread-ts $TS --channel C0CLLEH6D1N --post
uv run python scripts/marco_ops.py clash --start 2026-12-01 --end 2026-12-03 --place Lisbon --thread-ts $TS
```

If the gateway is down: `scripts/marco-up.sh` and wait for "connected". If all fails, play the demo video.

## After

The rehearsal messages (15:50 PT) are still in `#novato-trip`. Start the live demo below them, or in a fresh channel.
If you repeat beat 2 in a thread that already approved, Marco returns `already_done` while the events exist. Run "After" first.


```bash
jq -r '.calendar_event_ids[]' data/trip_novato.json | xargs -n1 -I{} uv run python -m services.gws calendar-delete --event-id {}
uv run python -m services.gws task-delete --task-id "$(jq -r .task_id data/trip_novato.json)"
```

The recorded run's trip state is kept in `data/ledger/trip_novato.recorded-run.json`.
