---
name: perk-booker
description: Plan, fill and (only after Tokyo approves) submit a Mindera work trip on Perk (app.perk.com) through the browser MCP, and document how to cancel it. Use it when Tokyo asks to book or plan a work trip, check a Perk fare again, or cancel a Perk request.
metadata: { "openclaw": { "requires": { "bins": ["uv"], "mcp": ["browsermcp"] } } }
---

# perk-booker

Marco drives Perk through the `browsermcp` `browser` tool, in Tokyo's logged-in Mindera Chrome.
This recipe was walked end to end on 2026-11-20 (trip <perk-trip-id>, OPO to SFO, Courtyard Novato).

## Fast path: stored options first (use this by default)

Live Perk searches take minutes. For a trip plan or proposal, **do not open the browser** when
stored data exists. Run from the repo root:

1. `cat data/trip_<place>.json`: the Marco trip id, the Perk draft (trip id, chosen flight,
   hotel, totals), and ground rides already reserved.
2. `cat data/perk_options_<place>.json`: the flight options with prices, alliance, times,
   policy and habit flags.
3. In parallel: `uv run python -m services.memory recall --query "<place> hotel breakfast flights habits"`
   and `uv run python -m services.policy ask --query "<cabin, hotel and ground rules for this trip>"`.
4. `uv run python -m services.router rank --json '{"task":"pick best value flight","options":[...],"facts":[...]}'`.
   If the router falls back to its heuristic, that is fine.
5. Write the **full chain** of audit rows in **one** call. Every row has real `sources` and a
   `model` (`anthropic/claude-sonnet-5-5`, or the router's model for `rank`). Use the `trip_id`
   from `data/trip_<place>.json`, so a later replan finds these rows.

```bash
uv run python -m services.audit record-many --json '[
 {"trip_id":"<id>","act":"book","step":"recall","status":"done","summary":"Recalled Novato hotel, breakfast and ground habits.","sources":[{"type":"cognee","ref":"<source_ref>","quote":"<fact>"}],"model":"anthropic/claude-sonnet-5-5","cost_usd":0.0,"external_ref":null,"supersedes":null,"approved_by":null},
 {... "step":"policy","status":"done", "sources":[{"type":"senso","ref":"<citation ref>","quote":"<citation quote>"}] ...},
 {... "step":"rank","status":"done", "model":"<router model or heuristic>", "sources":[{"type":"perk","ref":"data/perk_options_<place>.json","quote":"A KLM EUR 1411"}] ...},
 {... "step":"perk_fill","status":"proposed","external_ref":"<perk draft id>", "sources":[{"type":"perk","ref":"<itinerary url>","quote":"Saved in drafts"}] ...},
 {... "step":"calendar","status":"proposed", "sources":[{"type":"calendar","ref":"primary","quote":"<block you propose>"}] ...},
 {... "step":"uber_schedule","status":"proposed", "sources":[{"type":"web","ref":"https://riders.uber.com/trips","quote":"<ride or clash>"}] ...},
 {... "step":"notify","status":"done", "sources":[{"type":"slack","ref":"C0CKA55HJ31","quote":"Options A/B/C posted"}] ...}
]'
```

   One bad row writes nothing, so check the output for `"ids"`.
6. Post **one** thread message:
   - **Flights:** A) best value, B) the Star Alliance option that earns Miles&Go, C) the habit
     option and why it fails policy. Price, times, alliance for each.
   - **Hotel:** the memory fact with its source link.
   - **Ground:** rides already reserved (time, route, expense code). Flag any clash with the
     chosen flight times.
   - **Policy:** the Senso answer with one citation.
   - **Calendar:** the blocks you propose. Nothing is written yet.
   - The Perk draft id and total. Say that nothing is submitted.
   - Last line: `Reply "@Marco approve A", "B" or "C".`

Open the browser only when Tokyo asks for fresh prices, for a price watch (step 11), or to swap
or submit after his approval. When you do, use the existing draft (step 10b). Never start a new
search from `/home/flights` for a trip that already has a draft.

## Hard rules

1. **Approval gate.** Never press "Send approval request" until Tokyo replies "approve" from his own Slack member id (see `USER.md`). A name match is not enough. Record `perk_submit` as `proposed`, then as `approved` with `approved_by` set to that id.
2. Notes and the approver message both start with `HACKATHON TEST, DO NOT APPROVE.`
3. Never type a password. Never handle SSO, 2FA or passkey prompts. If you see one, stop and ask Tokyo. Press "Not now" on the "Add passkey" banner.
4. The checkout page shows the passport number, date of birth and loyalty numbers. Never copy them into Slack, audit rows, Cognee or logs.
5. One Perk tab only. Start **every** browser call with `tab select <perkTabId>`. Other agents drive other browsers ("Chrome 3", "Chrome 4") at the same time. Never touch their tabs.

## 0. Find the Perk tab

```
tab list
```

Pick the tab in browser `[Chrome]` whose URL starts with `https://app.perk.com`. Keep its id as `perkTabId`.
If none exists: `tab new --browser "Chrome" https://app.perk.com/home/flights`. A plain `tab new` opens in a different browser that is not logged in to Perk.
If the URL lands on a login or SSO page, stop and ask Tokyo.

## 1. Search flights

URL: `https://app.perk.com/home/flights`. Round-trip is the default.

```
tab select <perkTabId>
goto https://app.perk.com/home/flights
wait 3000
click getByPlaceholder('From')
fill getByPlaceholder('From') "OPO"
wait 1500
click getByRole('button', { name: /Porto.*OPO/ })
click getByPlaceholder('To')
fill getByPlaceholder('To') "SFO"
wait 1500
click getByRole('button', { name: /San Francisco Intl.*SFO/ })
click getByRole('button', { name: /Depart/ })
wait 1000
click getByRole('button', { name: 'Monday, November 30, 2026' })
click getByRole('button', { name: 'Friday, December 4, 2026' })
eval "() => [...document.querySelectorAll('input[type=date]')].map(i=>i.value).join(',')"
```

- Airport suggestions are buttons named `"<City> <Country> <IATA>"`. Use a regex on the IATA code.
- Date cells are buttons named with the full date, for example `'Monday, November 30, 2026'`. The calendar shows two months. Past days are disabled.
- If the first click on the date button does nothing, click it again (it toggles).
- The `eval` must print `2026-11-30,2026-12-04`. There is no "Apply" button.

```
tab select <perkTabId>
click getByRole('button', { name: 'Search flights' })
wait 20000
get url
```

The search creates a **draft trip at once**. The URL becomes
`https://app.perk.com/trips/<TRIP_ID>/search/flights/<searchId>?...&search_request=...`.
Read `TRIP_ID` from that URL. It is the Perk trip id (`external_ref`). A "Gathering the best offers..." dialog shows while results load. Wait for it to go.

## 1b. Offer options (before you pick anything)

Marco's job is best value, not habit. Do not fill the draft until Tokyo picks an option.

1. Turn on the in-policy filter: `click getByRole('button', { name: 'Policy', exact: true })`, then `click getByText(/In-policy only/)`, then `press Escape`.
2. Read pages 1 and 2 of results as compact text:

```
tab select <perkTabId>
eval "() => document.body.innerText.split('Luxury')[1].replace(/See journey details\n/g,'').replace(/Round trip\nfrom\n/g,'').replace(/\n/g,' ~ ').slice(0,3500)"
click getByRole('button', { name: 'Next page' })
wait 4000
```

3. Also read the habit option, for example TAP 07:00 with the Airlines filter (step 2).
4. For the top 4 or 5 options, open the fare panel (click the price button, for example `getByRole('button', { name: 'Round trip from €1,408 Light' })`) and record the change fee, refund terms and bags.
5. Build one object per option: `airlines, flights_out, alliance, depart_out, arrive_out, duration_out, stops_out, cabin, price_eur_round_trip, refundable, changeable, bags, in_policy, habit_match`. Save them to `data/perk_options_<place>.json` (the `data/` dir is gitignored).
   - The card price is "Round trip from €X". It is the cheapest round trip for that outbound. The real total depends on the return you pick.
   - Star Alliance (TAP, Lufthansa, United, SWISS, Brussels, Air Canada) earns Tokyo's TAP Miles&Go. SkyTeam (KLM, Air France, Delta) does not.
6. Rank them:

```bash
uv run python -m services.router rank --json '{"task":"pick best value flight","options":[...option objects...],"facts":[...memory facts from trip-memory recall...]}'
```

   Weigh price, then duration, then an arrival that fits the first meeting (allow about 1 h 30 min from SFO to Novato), and use Star Alliance as the tie-breaker.
7. Post 2 or 3 options to Tokyo in Slack. Example:

> You usually take TAP 07:00, but economy is sold out and business is out of policy (€4.7k).
> A) Best value: KLM via AMS, 05:00 to 11:45, 14h45, €1,411 return. In time for your Monday afternoon meeting. SkyTeam, so no Miles&Go.
> B) Lufthansa via FRA, 06:00 to 16:05, €1,295. Star Alliance, so your Miles&Go still earn. Lands too late for the meeting.
> C) Lufthansa via FRA, 12:30 to 20:10, €1,295. Star Alliance. Arrives in the evening.
> Reply A, B or C.

8. Wait for his reply. Then fill the draft with that option (steps 2 to 7). Record `perk_fill` with the chosen option in `summary`.

## 2. Pick the outbound flight

Filter by airline, then read the cards as text:

```
tab select <perkTabId>
click getByRole('button', { name: 'Airlines' })
wait 1000
click getByText(/^TAP Portugal \(\d+\)$/)
wait 3000
press Escape
get text --max 4000
```

- Each card lists: airline, flight numbers (`TP1939, TP237`), departure time, duration, stop, arrival, and "Round trip from €X <fare name>" per fare family.
- Fare families: Basic, Standard, Plus, Premium, Luxury. The "Fare options" filter shows the count per family. A `(0)` disabled checkbox means that family is sold out on that airline.
- Click the price of the card you want to open its fare panel. Anchor on the flight numbers, not on a price:

```
tab select <perkTabId>
eval "() => { const t=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&e.textContent.trim()==='TP1939, TP237'); let p=t; for(let i=0;i<12&&p;i++){p=p.parentElement; const f=[...p.querySelectorAll('*')].find(e=>e.children.length===0&&/^€[\d,]+$/.test(e.textContent.trim())); if(f){f.click(); return f.textContent;}} return 'not found'; }"
wait 3000
get text --max 4000
```

- The fare panel shows: policy status ("Out of policy" or nothing), fare name, cabin and booking class, round-trip price, "Changes: ...", refund terms ("Fully refundable" or not), bags.
- The "Select" button is often covered by an overlay. Use JS:

```
tab select <perkTabId>
eval "() => { const b=[...document.querySelectorAll('button')].filter(b=>b.innerText.trim()==='Select'); b[0].scrollIntoView(); b[0].click(); return b.length; }"
wait 8000
```

## 3. Pick the return flight

The page now shows "Return flight Fri, Dec 4" with the airline filter kept. Repeat step 2 for the return card. Prices on return cards are the **round-trip total** for that combination.

Then the "Configure your flight" page loads (seats, bags, total). It takes about 10 s ("Checking seat availability").

```
tab select <perkTabId>
wait 8000
get text --max 5000
click getByRole('button', { name: 'Continue to itinerary' })
wait 8000
get url
```

URL: `https://app.perk.com/trips/<TRIP_ID>/itinerary`.

## 4. Add the hotel to the same trip

Add it **from the itinerary page**. Do not use `/home/hotels`: that starts a new trip.

```
tab select <perkTabId>
click getByRole('button', { name: 'Stays', exact: true })
wait 3000
click getByPlaceholder('Search cities, hotels or points of interest')
type "Courtyard Novato"
wait 3000
click getByRole('button', { name: /^Courtyard Novato Marin\/Sonoma/ })
click getByRole('button', { name: /Check-in/ })
wait 1000
click getByRole('button', { name: 'Monday, November 30, 2026' })
click getByRole('button', { name: 'Thursday, December 3, 2026' })
eval "() => [...document.querySelectorAll('input[type=date]')].map(i=>i.id+'='+i.value).join(',')"
click getByRole('dialog').getByRole('button', { name: 'Search stays' })
wait 10000
get text --max 3000
```

- The `eval` must print `hotel-checkin=2026-11-30,hotel-checkout=2026-12-03`.
- The results list shows per hotel: "Free cancellation", "Breakfast" or "No breakfast", total and per-night price.
- **Clicking a hotel card opens a new tab.** Read its URL, close it, and `goto` that URL in the Perk tab:

```
tab list
tab select <newTabId>
get url
tab close
tab select <perkTabId>
goto <that url>
wait 10000
```

Hotel URL shape: `https://app.perk.com/trips/<TRIP_ID>/search/stays/<searchId>/result/<hotelId>/<hotelId>/amadeus_hotels_gds?checkinDate=...&checkoutDate=...`.

Pick the room and the rate:

```
tab select <perkTabId>
eval "() => { const h=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&e.textContent.trim()==='King Room'); let p=h; for(let i=0;i<10;i++){p=p.parentElement; const b=[...p.querySelectorAll('button,a')].find(b=>b.innerText.trim()==='View'); if(b){b.click(); return 'clicked';}} return 'no'; }"
wait 3000
get text --max 6000
snapshot -i getByRole('dialog').last()
```

- The "Rate details" dialog lists rates, for example "Standard: Not refundable, no breakfast" and "Flexible: Cancel before <date>, no breakfast". The rate radios have no names. Take the radio in the same order as the text. Pick the one that says "Cancel before" and "no breakfast" (room only).
- Then `click getByRole('button', { name: 'Select rate' })`. The "Review stay details" view shows "Free cancellation before <date> <time>", the total, and "Pay in advance".
- `click getByRole('button', { name: 'Continue to itinerary' })`.

## 5. Name the trip

On `/trips/<TRIP_ID>/itinerary`:

```
tab select <perkTabId>
click getByRole('button', { name: 'Edit name' })
fill getByPlaceholder('Give this trip a name') "2K AI workshop Novato (HACKATHON TEST)"
press Enter
wait 2000
get value getByPlaceholder('Give this trip a name')
get text --max 6000
```

The itinerary text shows each item, "Out of policy" flags, the hotel cancellation date, "Total price of trip", and "You'll need to request approval in the next step". "Saved in drafts" means nothing is booked yet.

Write the `perk_fill` audit row now (see "Audit rows").

## 6. Checkout form

```
tab select <perkTabId>
click getByRole('button', { name: 'Continue to checkout' })
wait 10000
get url
```

URL: `https://app.perk.com/checkout/<TRIP_ID>?from=itinerary&preselect=true`.
"Continue to checkout" is disabled while the itinerary loads. Wait and retry.

Payment and reporting fields (all react-select comboboxes; list options with
`eval "() => [...document.querySelectorAll('[role=option]')].map(o=>o.innerText).join(' | ')"` after you open one):

| Field | Target | Value for 2K work | Options seen |
|---|---|---|---|
| Payment profile | read only | "Thinkit Solutions Limited - Manual SEPA" (prefilled) | - |
| Cost object (Mandatory) | `getByRole('combobox', { name: /Cost object/ })` | `getByRole('option', { name: '2k', exact: true })` | client list: 2k, ASOS, Farfetch, ..., Mindera Labs, None |
| Billable to client (Mandatory) | `getByRole('combobox', { name: /Billable to client/ })` | `Yes, billable` | `No, not billable (Mindera cost)`, `Yes, billable` |
| Description of the Trip (Mandatory) | `getByRole('combobox', { name: /Description of the Trip/ })` | `Client Visit` | Client Visit, Mindera Strategy, Other, Promotion and Events, Team Gathering (Mindera internal), Training |
| Labels | optional | skip | - |
| Notes (free text, max 160 chars) | `getByRole('textbox', { name: 'Notes' })` | the description below | - |
| Vertical (Mandatory) | `getByRole('combobox', { name: /Vertical/ })` | `Gaming` | FashionTech, FinTech, Gaming, General, Investment, Mindera, Mindera Ops, Miscellaneous, Public Sector, Retail, Telecom, Travel & Transportation |
| Message for the approver (max 500) | `getByRole('textbox', { name: /Message for the approver/ })` | starts with the DO NOT APPROVE note | shows only when an item is out of policy |

"Description of the Trip" is a category dropdown, not free text. The free-text trip description goes in **Notes**:

```
HACKATHON TEST, DO NOT APPROVE. Approved by the commercial approver (Mindera). Billable to 2K (Take-Two). Area: Novato, CA, near 2K office.
```

That is 129 chars. Keep it under 160.

```
tab select <perkTabId>
click getByRole('combobox', { name: /Cost object/ })
wait 1500
click getByRole('option', { name: '2k', exact: true })
click getByRole('combobox', { name: /Billable to client/ })
wait 1000
click getByRole('option', { name: 'Yes, billable' })
click getByRole('combobox', { name: /Description of the Trip/ })
wait 1000
click getByRole('option', { name: 'Client Visit' })
click getByRole('combobox', { name: /Vertical/ })
wait 1000
click getByRole('option', { name: 'Gaming' })
press Escape
fill getByRole('textbox', { name: 'Notes' }) "HACKATHON TEST, DO NOT APPROVE. Approved by the commercial approver (Mindera). Billable to 2K (Take-Two). Area: Novato, CA, near 2K office."
eval "() => document.body.innerText.split('Payment and reporting')[1]"
```

If out of policy, also fill the approver message:

```
fill getByRole('textbox', { name: /Message for the approver/ }) "HACKATHON TEST, DO NOT APPROVE. <one line why>"
```

## 7. Final screen: read, screenshot, stop

```
tab select <perkTabId>
find "Send approval request"
find "An approval request will be sent to"
scroll getByRole('button', { name: 'Send approval request' })
screenshot
```

`screenshot` saves a JPEG and prints its path. Send that path and the summary to Tokyo.

What the page says (seen 2026-11-20):

- Button: **"Send approval request"**, under the heading "Request approval".
- Under it: "This booking can't be confirmed until your request is approved".
- "An approval request will be sent to **Mindera PT**." This is the approver group, not a named person. Past approved trips show "the facilities approver".
- Out-of-policy reason, for example: "The cabin class is not allowed. Only Economy or Economy-comfort can be booked for this route."
- Price breakdown: each item, then "Fees" (about 10% here), then "Total", then "This trip will be invoiced in GBP at £X". The checkout total includes fees; the itinerary total does not.
- No card entry. Payment goes through the company SEPA profile on invoice.

So pressing the button sends an **approval request**. It does not book or charge. Perk books only after the approver approves. If the approver approves, booking and the invoice follow, so the DO NOT APPROVE note is the safety net.

Pre-submit checklist. Press only if all hold, and only after Tokyo's "approve":

1. The page says "Send approval request" and "can't be confirmed until your request is approved". No "Book", "Pay" or "Confirm booking" wording.
2. Notes (and approver message, if shown) start with `HACKATHON TEST, DO NOT APPROVE.`
3. Every item is refundable: flight "Fully refundable" or FlexiTravel, hotel "Free cancellation before <date>" with the date still in the future.
4. Cost object is set (2k for 2K work).

## 8. Submit (write step, gated)

```
tab select <perkTabId>
click getByRole('button', { name: 'Send approval request' })
wait 8000
get url
get text --max 3000
screenshot
```

Then open `https://app.perk.com/trips` and confirm the trip shows under "Needs action" or as pending approval. Write the `perk_submit` row with status `done`.

## 9. Cancel or withdraw

- **Draft (not submitted):** on `https://app.perk.com/trips`, Drafts section, the trip card has "Delete trip". The itinerary page also has `getByRole('button', { name: 'Delete Trip' })`. The checkout page has `getByRole('button', { name: 'Delete' })`.
- **Pending approval:** not yet verified live (no request was sent on 2026-11-20). Expected path: `https://app.perk.com/trips`, tab "Needs action" (or "All"), open the trip card, then look for "Cancel request", "Withdraw" or "Delete trip". Run `find "Cancel"` and `find "Withdraw"` on the trip page, and read the confirm dialog before you press. A pending request has no booking, so cancel has no fee.
- **Confirmed booking:** open the trip, use each item's cancel action. Read the fee first. FlexiTravel refunds at least 80% in credits. Hotel flexible rates are free before their cancel date.
- After cancel, the trip moves to the "Canceled" tab. Write a `perk_cancel` row.

After the demo, cancel every HACKATHON TEST request (workspace rule 6).

## 10. Price and fare details (for price watch)

- The search URL is replayable. `goto` the saved `/trips/<TRIP_ID>/search/flights/<searchId>?...&search_request=...&filters=...` URL in the Perk tab. It re-runs the search and shows **current** fares with the same filters. Tested: it reloaded TAP fares in about 20 s.
- Read the price with `get text` on the card ("Round trip from €X <fare>").
- The fare panel (click a price) shows refund and change terms, cabin and booking class.
- Itinerary page: "Total price of trip" (no fees). Checkout page: per-item breakdown, fees, total and GBP invoice amount.
- Hotel result URL with `checkinDate` and `checkoutDate` also replays and shows current room rates.

## 10b. Swap the flight in an existing draft

Do not start a new search from `/home/flights`. Use the flight item's "Edit" link on the itinerary. It replaces the flight and keeps the hotel, name and checkout fields:

```
tab select <perkTabId>
goto https://app.perk.com/trips/<TRIP_ID>/itinerary
eval "() => [...document.querySelectorAll('a')].map(a=>a.getAttribute('href')).filter(h=>h&&h.includes('service-search/flight')).join('\n')"
goto https://app.perk.com/trips/<TRIP_ID>/itinerary/service-search/flight?booking_request=<id>
wait 3000
click getByRole('dialog').getByRole('button', { name: 'Search flights' })
wait 25000
```

Then pick the outbound and the return (steps 2 and 3). A cheapest fare ("Light") opens a "Does Light fit your travel needs?" upsell dialog. Press `getByRole('button', { name: 'Continue', exact: true })` to keep it, or "Upgrade for €X". After "Continue to itinerary", re-check the checkout fields and update the approver message so it matches the new flight.

## 11. Price watch

1. Store the option's search URL, fare name and `price_eur_round_trip` with the trip (audit row `sources` or the options file).
2. On a schedule, `goto` the saved search URL in the Perk tab and `wait 20000`.
3. Read the same card (anchor on the flight numbers) and the same fare name. Also check the habit option (for example TAP 07:00 economy).
4. Propose a swap to Tokyo in Slack if either holds:
   - the same or an equal option is at least 5% cheaper than the stored price, or
   - a habit-match fare comes back in policy (for example TAP 07:00 economy).
5. Swap only after his reply (step 10b). Never swap after the request is submitted without Tokyo's ok. A submitted request needs a cancel and a new request.

## Failure modes

| Symptom | Meaning | Action |
|---|---|---|
| "Fare options" shows Basic/Standard/Plus/Premium `(0)` and only Luxury | Economy sold out on that airline | Report it. Offer the cheapest in-policy option (use the "Policy" filter). Do not pick business without Tokyo's ok. |
| "Out of policy" on a card or item | Breaks Mindera travel policy (cabin, price) | Checkout then needs "Message for the approver". Tell Tokyo the reason text. |
| Wanted flight not in results | Sold out or not offered | Clear filters ("Reset filters"), check page 2+, then propose the closest match by time and airline. |
| Hotel rate shows only "Not refundable" | No free cancellation | Pick another room or hotel with "Free cancellation" (filter on the results page). |
| Hotel cancel date already passed | Free cancellation ended | Treat as non-refundable. Ask Tokyo. |
| Cost object has no matching client | Missing cost centre | List the options to Tokyo. Do not guess. "None" is valid only for internal trips. |
| "Continue to checkout" disabled | Itinerary still loading | `wait 3000` and retry. |
| `click` says "is covered by" | Overlay or sticky bar | Use the JS `eval` click shown in step 2. |
| Clicking a hotel opens a new tab | Perk opens results in new tabs | Read its URL, close it, `goto` in the Perk tab. |
| Login, SSO, 2FA or passkey prompt | Session expired | Stop. Ask Tokyo. Never type credentials. |
| Price changed at checkout | Fares move | Report old and new price to Tokyo before submit. |

## Audit rows

Run from the repo root. One row per step: first `proposed`, then `done` or `failed`. `external_ref` is the Perk trip id.

```bash
uv run python -m services.audit record --json '{"trip_id":"<marco trip id>","step":"perk_fill","status":"done","summary":"Marco filled Perk trip <perk-trip-id>: TAP OPO-SFO 30 Nov, return 4 Dec, Courtyard Novato 3 nights. Total EUR 5854.04.","sources":[{"type":"perk","ref":"https://app.perk.com/trips/<perk-trip-id>/itinerary","quote":"Saved in drafts"}],"model":null,"cost_usd":0.0,"external_ref":"<perk-trip-id>","supersedes":null,"approved_by":null}'

uv run python -m services.audit record --json '{"trip_id":"<marco trip id>","step":"perk_submit","status":"proposed","summary":"Marco proposes to send the Perk approval request for trip <perk-trip-id>.","sources":[{"type":"perk","ref":"https://app.perk.com/checkout/<perk-trip-id>","quote":"An approval request will be sent to Mindera PT."}],"model":null,"cost_usd":0.0,"external_ref":"<perk-trip-id>","supersedes":null,"approved_by":null}'

uv run python -m services.audit record --json '{"trip_id":"<marco trip id>","step":"perk_submit","status":"done","summary":"Marco sent the Perk approval request for trip <perk-trip-id>. It is pending approval.","sources":[{"type":"perk","ref":"https://app.perk.com/trips","quote":"Needs action"}],"model":null,"cost_usd":0.0,"external_ref":"<perk-trip-id>","supersedes":"<id of the proposed row>","approved_by":"<Tokyo slack member id>"}'

uv run python -m services.audit record --json '{"trip_id":"<marco trip id>","step":"perk_cancel","status":"done","summary":"Marco cancelled the Perk request for trip <perk-trip-id>.","sources":[{"type":"perk","ref":"https://app.perk.com/trips","quote":"Canceled"}],"model":null,"cost_usd":0.0,"external_ref":"<perk-trip-id>","supersedes":null,"approved_by":"<Tokyo slack member id>"}'
```

Never put passport, loyalty or card numbers in `summary` or `quote`.

## Reference: the 2026-11-20 walk (trip <perk-trip-id>)

- Outbound: TAP TP1939 + TP237, Mon 30 Nov 07:00 OPO, via LIS, 14:25 SFO. Only "Top Executive" (Business C) was left. Out of policy. Fully refundable.
- Return: TAP TP8493 (operated by United) + TP212, Fri 4 Dec 12:00 SFO, via EWR, 11:00 OPO +1. Economy "Plus". The combined round trip was €4,734.26.
- Hotel: Courtyard Novato Marin/Sonoma, King Room, Flexible rate, room only, €587.60, free cancellation before 21 Nov 2026 18:00 local.
- Checkout total €5,854.04 with €532.19 fees (invoiced as £4,903.45).
- Cheaper in-policy flights existed: Lufthansa LH1175 from €1,295, KLM KL1570 05:00 from €1,408.
- Tokyo chose "in policy, best value". The draft flight was then swapped (step 10b) to KLM KL1570+KL605 (05:00 OPO, 11:45 SFO) and KL5639+KL6201 (09:10 SFO, 08:15 OPO +1), Economy Light, €1,411.27. New checkout total: €2,198.76 including €199.89 fees. No item is out of policy.
- Options data: `data/perk_options_novato.json`.
- Not submitted. It stays a draft.
