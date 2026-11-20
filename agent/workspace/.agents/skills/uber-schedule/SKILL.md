---
name: uber-schedule
description: Schedule (Reserve) or cancel an Uber ride for a trip through the browser MCP. Use it after Tokyo approves a trip that needs an airport or office ride. Uses the Mindera business profile and an expense code.
metadata: { "openclaw": { "requires": { "bins": ["uv"] } } }
---

# uber-schedule

Marco drives Uber in Tokyo's logged-in Chrome with the `browser` tool (browsermcp). Tested on 2026-11-20.

## Rules

- **Approval gate.** Never press the final button until Tokyo replies "approve" from his own member id (see `USER.md`). First record `proposed`, then `approved` with `approved_by`.
- Never type a password. Never enter or change payment details. If Uber asks for login, 2FA or payment, stop and tell Tokyo.
- Start every browser call with `tab select <uber tab id>`. Find the id with `tab list` (tab title "Plan your Uber journey" or "Uber"). Other agents share the browser.
- Use the Mindera business profile only. Billing must read "Billed to company".
- Tell Tokyo the cancel fee before you cancel.

## Change the time of a reserved ride

Uber "Edit" (`/go/reserved/<id>/select-time`) only offers dates in the next 7 days. Seen 2026-11-20:
every date after 27 Nov reads "Not available", and the page resets to today.
For a later ride: cancel it (free up to 1 h before, see "Cancel"), then run the schedule recipe
again with the new time. Record `uber_cancel` and `uber_schedule` rows with both reservation ids.

## Schedule recipe

Limits: Uber allows booking up to 90 days ahead. Times use 10-minute steps. Pick-up window is "Pick-up at" (default).

1. `goto https://m.uber.com/go/reserve` (redirects to `/go/reserve/home`). Saved places were empty on the test day, so type the pickup.
2. Pickup: `click getByRole('combobox', { name: 'Search for a location' }).first()`, `type "Palo Alto Caltrain Station"`, `wait 2000`, `click getByText('95 University Ave')`. Use the street line, not the name: "Palo Alto Station" and "Northbound" both match by name.
3. Drop-off: `click getByRole('combobox', { name: 'Search for a location' }).nth(1)`, `type "San Francisco International Airport"`, `wait 2000`, `click getByText('780 McDonnell Rd')`. The page moves to `/select-time`.
4. Date: `click getByRole('textbox', { name: 'Select a date.' })`, then `click getByRole('gridcell', { name: /Friday, December 4th 2026/ })`. Past or too-far days read "Not available".
5. Time: `click getByText('1:00 PM')` (the combobox shows the default), then `click getByRole('option', { name: '10:00 AM', exact: true })`. Check the URL: `pickup_formatted_time=2026-12-04T10:00:00`. Then `click getByRole('button', { name: 'Next' })`.
6. Product page (`/product-selection`). Read the benefits text. It must say: "Cancel at no charge up to 60 minutes in advance". If it does not, STOP.
7. Profile: the page resets to Personal each time (the card may read "Expired"). `click getByRole('button', { name: 'Change payment method' })`. A dialog holds an iframe. Use snapshot refs (`f5eNN`) inside it, since role targets do not cross the iframe. Click the "Briefcase Business" option, then the "Mindera" button, then "Save". Verify `get text main` shows "Mindera" and "Billed to company". Rides then show "In policy".
8. Ride type: `click getByRole('option', { name: /^UberX4/ })` (selected by default).
9. `click getByRole('button', { name: 'Reserve trip' })`. A pickup refinement page follows ("Confirm the pick-up location"). Station pickups offer Northbound or Southbound. SFO is north of Palo Alto, so keep "Northbound Pick-Ups". Click `Reserve trip` again.
10. A dialog "Requesting your ride" opens with `getByRole('textbox', { name: 'Search expense code' })`. `fill` it with the client name, e.g. `2K`. If the list has a match, click it, then "Next". If it shows "No matching expense codes", click `getByRole('button', { name: 'Add as custom expense code' })`.
11. **The expense step is the confirm step.** Adding the code reserves the ride at once. Do steps 9 to 11 only after approval.
12. Success page `/go/reserved/<reservation_id>` says "Thank you for reserving your ride", "UberX reserved", time, fare, "Mindera", and "Cancel at no charge up to one hour in advance". Read the id from `get url`.
13. Verify: `goto https://riders.uber.com/trips`. Under "Upcoming" a card reads "Confirmed / UberX / 4 Dec, 10:00 PST".

The expense code does not show on the reservation page. Uber stores it with the trip. Do not retry to check it, because a retry could create a second ride.

## Cancel recipe

1. `goto https://riders.uber.com/reservation/<reservation_id>`. Also reachable from `riders.uber.com/trips` -> "Trip details".
2. `click getByRole('button', { name: 'Cancel this trip' })`. Free until 60 minutes before pick-up. Inside that window Uber may show a fee. Read it, tell Tokyo, and wait for approval.
3. Confirm in the dialog. Do not use "Edit": it only changes the time (`/go/reserved/<id>/select-time`).
4. Verify the card leaves "Upcoming" and appears as "Cancelled" under Past.

Not tested live: the cancel dialog text (the demo ride must stay until the demo ends).

## Limits and failure modes

- A second ride on another day opens the flow without any limit text up to the product page. The limit, if any, shows only at confirm. Never confirm a second ride in a test.
- `Not available` date: the day is past or more than 90 days away. Choose the nearest "available" day.
- Personal card "Expired": you are on the wrong profile. Switch to Business (step 7).
- Console errors `ERR_FAILED` or `404` are noise. Ignore them.
- The edit URL shows another time in `pickup_formatted_time`. Trust the success page, not that parameter.
- Login, 2FA or payment prompt: stop and report to Tokyo.

## Audit

Run from the repo root after each step (`proposed` before, `done` or `failed` after). Use the reservation id as `external_ref`.

```
uv run python -m services.audit record --json '{"trip_id":"<trip_id>","step":"uber_schedule","status":"done","summary":"UberX reserved Fri 4 Dec 10:00 PT, Palo Alto Caltrain to SFO, Mindera profile, code 2K.","sources":[],"model":null,"cost_usd":0.0,"external_ref":"<reservation_id>","supersedes":null,"approved_by":"<slack member id>"}'
uv run python -m services.audit record --json '{"trip_id":"<trip_id>","step":"uber_cancel","status":"cancelled","summary":"Reservation cancelled, no fee.","sources":[],"model":null,"cost_usd":0.0,"external_ref":"<reservation_id>","supersedes":"<schedule row id>","approved_by":"<slack member id>"}'
```

Check `docs/contracts.md` for the exact row fields. Never put card numbers in a row.
