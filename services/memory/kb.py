"""Obsidian vault in kb/: build from seed facts, append actions from Marco."""
import re
from datetime import date
from pathlib import Path

KB = Path(__file__).resolve().parents[2] / "kb"
NUM = re.compile(r"\d{6,}")  # reservation-like numbers never enter the vault


def clean(s) -> str:
    return NUM.sub("[redacted]", str(s))


def _page(path: str, title: str, typ: str, topic: str, sources: list[str], body: str, root: Path = None):
    root = root or KB
    p = root / "wiki" / path
    p.parent.mkdir(parents=True, exist_ok=True)
    src = "\n".join(f"  - {clean(s)}" for s in sources) or "  - seed"
    p.write_text(
        f"---\ntitle: {title}\ntype: {typ}\ntopic: {topic}\nsources:\n{src}\n"
        f"last_verified: {date.today().isoformat()}\n---\n\n# {title}\n\n{clean(body).strip()}\n"
    )


TOKYO = """Tokyo is Director of Applied AI at Mindera. Marco is his chief-of-staff agent.

## Home and base
- Lives in [[places/porto]]. Flies from OPO.
- Spends Thanksgiving in Palo Alto and flies home to Portugal on 4 to 5 December.

## Where he travels
- [[places/novato]] for 2K work.
- [[places/dublin]] for Mindera work.
- [[places/san-francisco]] for the US flights.

## How he travels
- [[preferences/short-notice-booking]]
- [[preferences/room-only-breakfast]]
- [[preferences/late-friday-extension]]
- [[preferences/flexitravel]]
- [[preferences/uber-expense-code]]
- [[preferences/ground-transport-us]]

## Approval
See [[approval/perk-flow]].

## Hotels and trips
[[hotels/courtyard-novato]], [[hotels/the-dean-dublin]], [[hotels/albany-house-dublin]].
[[trips/novato-2k-nov-2026]], [[trips/dublin-oct-2026]], [[trips/dublin-sep-2026]], [[trips/opo-sfo-nov-2026]], [[trips/novato-2k-workshop-dec-2026]].
"""

PAGES = [
    ("traveller/tokyo.md", "Tokyo", "traveller", "profile", ["slack", "gmail"], TOKYO),
    ("places/novato.md", "Novato", "place", "place", ["slack"],
     "2K client site. Billable to 2K. Approver on the Mindera side: the commercial approver.\n\n- Hotel: [[hotels/courtyard-novato]]\n- Trips: [[trips/novato-2k-nov-2026]], [[trips/novato-2k-workshop-dec-2026]]\n- Ground: [[preferences/ground-transport-us]]\n- Habits: [[preferences/room-only-breakfast]], [[preferences/late-friday-extension]]\n- Traveller: [[traveller/tokyo]]"),
    ("places/dublin.md", "Dublin", "place", "place", ["gmail", "slack"],
     "Mindera work trips. Flights on Ryanair from OPO.\n\n- Hotels: [[hotels/the-dean-dublin]], [[hotels/albany-house-dublin]]\n- Trips: [[trips/dublin-oct-2026]], [[trips/dublin-sep-2026]]\n- Lesson: confirm the hotel 48 hours before arrival. See [[preferences/confirm-hotel-48h]].\n- Traveller: [[traveller/tokyo]]"),
    ("places/san-francisco.md", "San Francisco", "place", "place", ["slack"],
     "Arrival airport for US trips. Tokyo flies OPO to SFO on TAP via Lisbon.\n\n- Trip: [[trips/opo-sfo-nov-2026]]\n- Next stop: [[places/novato]]\n- Preference: [[preferences/flexitravel]]\n- Traveller: [[traveller/tokyo]]"),
    ("places/porto.md", "Porto", "place", "place", ["slack"],
     "Home base. Airport code OPO. Portugal trips need approval from facilities.\n\n- Approval: [[approval/perk-flow]]\n- Trips from here: [[trips/opo-sfo-nov-2026]], [[trips/dublin-oct-2026]]\n- Traveller: [[traveller/tokyo]]"),
    ("hotels/courtyard-novato.md", "Courtyard Novato Marin/Sonoma", "hotel", "hotel", ["slack"],
     "Standard hotel for 2K visits. Room: one king bed with sofa bed. Room only.\n\n- Place: [[places/novato]]\n- Trips: [[trips/novato-2k-nov-2026]]\n- Preference: [[preferences/room-only-breakfast]], [[preferences/late-friday-extension]]"),
    ("hotels/the-dean-dublin.md", "The Dean Dublin Centre", "hotel", "hotel", ["gmail", "slack"],
     "Harcourt Street. Room: The Large, breakfast included. Current Dublin choice.\n\n- Place: [[places/dublin]]\n- Trip: [[trips/dublin-oct-2026]]\n- Lesson: [[preferences/confirm-hotel-48h]]"),
    ("hotels/albany-house-dublin.md", "Albany House Dublin", "hotel", "hotel", ["gmail"],
     "Harcourt Street. Breakfast included. Non-refundable. Earlier choice.\n\n- Place: [[places/dublin]]\n- Trip: [[trips/dublin-sep-2026]]\n- Newer option: [[hotels/the-dean-dublin]]"),
    ("trips/novato-2k-nov-2026.md", "Novato 2K visit, November 2026", "trip", "trip", ["slack", "gmail"],
     "Past trip. Tokyo extended the hotel by one night after a late Friday finish (12 to 13 Nov).\n\n- Hotel: [[hotels/courtyard-novato]]\n- Place: [[places/novato]]\n- Habit: [[preferences/late-friday-extension]]\n- Approval: [[approval/perk-flow]]"),
    ("trips/novato-2k-workshop-dec-2026.md", "Novato 2K AI workshop, 30 Nov to 2 Dec 2026", "trip", "trip", ["slack"],
     "Bart's 2K AI workshop is in Novato, Mon 30 Nov to Wed 2 Dec 2026. Tokyo leads it with the client lead and the commercial approver.\n\n- Place: [[places/novato]]\n- Hotel: [[hotels/courtyard-novato]]\n- Approval: [[approval/perk-flow]]"),
    ("trips/dublin-oct-2026.md", "Dublin trip, October 2026", "trip", "trip", ["gmail"],
     "Ryanair FR7073 from OPO, evening. Hotel [[hotels/the-dean-dublin]].\n\n- Place: [[places/dublin]]\n- Lesson: [[preferences/confirm-hotel-48h]]"),
    ("trips/dublin-sep-2026.md", "Dublin trip, September 2026", "trip", "trip", ["gmail"],
     "Hotel [[hotels/albany-house-dublin]], breakfast included, non-refundable.\n\n- Place: [[places/dublin]]"),
    ("trips/opo-sfo-nov-2026.md", "OPO to SFO, November 2026", "trip", "trip", ["slack", "gmail"],
     "TAP TP1939 at 07:00 on Monday OPO to Lisbon, then TP237 to SFO, arriving 14:25. Economy comfort. FlexiTravel added.\n\n- Places: [[places/porto]], [[places/san-francisco]], [[places/novato]]\n- Preference: [[preferences/flexitravel]], [[preferences/short-notice-booking]]"),
    ("preferences/room-only-breakfast.md", "Room only, own breakfast", "preference", "habit", ["slack"],
     "In Novato Tokyo books room only. He buys breakfast himself (for example at Safeway) and expenses it. Included hotel breakfast changes the per diem: register it in Mindera People.\n\n- Place: [[places/novato]]\n- Hotel: [[hotels/courtyard-novato]]\n- Contrast: [[hotels/the-dean-dublin]] includes breakfast."),
    ("preferences/late-friday-extension.md", "Extend one night after a late Friday", "preference", "habit", ["gmail"],
     "When Tokyo finishes late on a Friday in Novato, he extends the hotel by one night.\n\n- Hotel: [[hotels/courtyard-novato]]\n- Trip: [[trips/novato-2k-nov-2026]]"),
    ("preferences/flexitravel.md", "FlexiTravel on long-haul", "preference", "flight", ["gmail"],
     "Tokyo adds FlexiTravel on long-haul Perk bookings. The trip stays 80 percent refundable.\n\n- Trip: [[trips/opo-sfo-nov-2026]]\n- Place: [[places/san-francisco]]"),
    ("preferences/short-notice-booking.md", "Short-notice booking", "preference", "habit", ["gmail"],
     "Tokyo books 1 to 3 days before departure. He avoids losing a working day: he flies the evening before or the morning of the first meeting.\n\n- Trip: [[trips/opo-sfo-nov-2026]]\n- Flow: [[approval/perk-flow]]"),
    ("preferences/uber-expense-code.md", "Uber expense code is the client", "preference", "ground", ["slack"],
     "Use the Mindera Uber for Business profile. The expense code is the client name, for example 2K, not travel.\n\n- Place: [[places/novato]]\n- See also: [[preferences/ground-transport-us]]"),
    ("preferences/ground-transport-us.md", "Ground transport in the US", "preference", "ground", ["slack"],
     "Tokyo uses Uber and drives. Palo Alto to Novato by Uber costs about 60 USD each way. He does not book rental cars on Perk.\n\n- Place: [[places/novato]]\n- Rule: [[preferences/uber-expense-code]]"),
    ("preferences/confirm-hotel-48h.md", "Confirm hotel 48 hours before arrival", "preference", "habit", ["slack"],
     "In November the Dublin hotel did not have Tokyo's reservation at check-in. Confirm the booking 48 hours before arrival.\n\n- Place: [[places/dublin]]\n- Hotel: [[hotels/the-dean-dublin]]"),
    ("approval/perk-flow.md", "Perk approval flow", "approval", "approval", ["slack", "drive"],
     """Every Perk trip needs a cost centre and a trip description, then Request Approval.

1. The facilities approver approves Portugal and 2K trips.
2. For 2K work, the commercial approver approves on the Mindera side. The trip is billable to 2K.
3. Facilities need three facts before booking: who approved, who pays, and the city and area.
4. After the trip: register it in Mindera People as project travel. File receipts in Rydoo with the Mindera VAT number.
5. Per diem covers meals on all travel days.

Marco plans the trip and stops before Request Approval. A human presses the button.

- Traveller: [[traveller/tokyo]]
- Places: [[places/novato]], [[places/porto]]
- Trips: [[trips/novato-2k-nov-2026]]"""),
]

INDEX = """---
title: Marco Knowledge Base
type: index
topic: index
sources:
  - seed
last_verified: {d}
---

# Marco Knowledge Base

Demo-safe memory of Tokyo's travel. Facts only. No card, passport, plate or reservation numbers.

## Traveller
- [[wiki/traveller/tokyo]]

## Places
[[wiki/places/novato]], [[wiki/places/dublin]], [[wiki/places/san-francisco]], [[wiki/places/porto]]

## Hotels
{hotels}

## Trips
{trips}

## Preferences
{prefs}

## Approval
- [[wiki/approval/perk-flow]]

See also [[log]].
"""


def _links(prefix: str, root: Path) -> str:
    d = root / "wiki" / prefix
    return "\n".join(f"- [[wiki/{prefix}/{p.stem}]]" for p in sorted(d.glob("*.md")))


def _index(root: Path):
    (root / "index.md").write_text(INDEX.format(
        d=date.today().isoformat(), hotels=_links("hotels", root),
        trips=_links("trips", root), prefs=_links("preferences", root)))


def build_vault(facts=None, root: Path = None) -> dict:
    root = root or KB
    (root / ".obsidian").mkdir(parents=True, exist_ok=True)
    (root / ".obsidian" / "app.json").write_text('{\n  "alwaysUpdateLinks": true,\n  "showUnsupportedFiles": false\n}\n')
    (root / ".obsidian" / "core-plugins.json").write_text(
        '{\n  "file-explorer": true,\n  "global-search": true,\n  "graph": true,\n  "backlink": true,\n'
        '  "outgoing-link": true,\n  "page-preview": true,\n  "properties": true,\n  "tag-pane": true,\n  "outline": true\n}\n')
    (root / ".obsidian" / "graph.json").write_text(
        '{\n  "showTags": false,\n  "showOrphans": true,\n  "colorGroups": [\n'
        '    {"query": "path:wiki/hotels", "color": {"a": 1, "rgb": 14701138}},\n'
        '    {"query": "path:wiki/trips", "color": {"a": 1, "rgb": 5431378}},\n'
        '    {"query": "path:wiki/preferences", "color": {"a": 1, "rgb": 11141375}}\n  ]\n}\n')
    for path, title, typ, topic, src, body in PAGES:
        p = root / "wiki" / path
        if not p.exists():  # keep pages that kb_write has updated
            _page(path, title, typ, topic, src, body, root)
    if not (root / "log.md").exists():
        (root / "log.md").write_text("# Log\n\nAppend-only. One line per action.\n\n")
    with open(root / "log.md", "a") as f:
        f.write(f"## [{date.today().isoformat()}] seed | vault built from seed facts\n")
    _index(root)
    return {"pages": len(PAGES), "root": str(root)}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "trip"


def kb_write(entry: dict, root: Path = None) -> dict:
    """Append to log.md and create or update a trip page.

    entry keys: trip_id (required), title, action, status, summary, place, hotel, sources.
    """
    root = root or KB
    trip = _slug(entry["trip_id"])
    action = clean(entry.get("action", "update"))
    status = clean(entry.get("status", ""))
    summary = clean(entry.get("summary", ""))
    now = date.today().isoformat()
    root.mkdir(parents=True, exist_ok=True)
    log = root / "log.md"
    if not log.exists():
        log.write_text("# Log\n\nAppend-only. One line per action.\n\n")
    with open(log, "a") as f:
        f.write(f"## [{now}] {action} | [[wiki/trips/{trip}]] {status} {summary}".rstrip() + "\n")
    page = root / "wiki" / "trips" / f"{trip}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {now} {action} {status}: {summary}".rstrip()
    if page.exists():
        text = page.read_text()
        text = re.sub(r"last_verified: .*", f"last_verified: {now}", text, count=1)
        if "## Actions" not in text:
            text += "\n## Actions\n"
        text = text.rstrip("\n") + "\n" + line + "\n"
    else:
        links = []
        if entry.get("place"):
            links.append(f"- Place: [[places/{_slug(entry['place'])}]]")
        if entry.get("hotel"):
            links.append(f"- Hotel: [[hotels/{_slug(entry['hotel'])}]]")
        links += ["- Flow: [[approval/perk-flow]]", "- Traveller: [[traveller/tokyo]]"]
        src = "\n".join(f"  - {clean(s)}" for s in entry.get("sources", ["marco"]))
        text = (f"---\ntitle: {clean(entry.get('title', trip))}\ntype: trip\ntopic: trip\nsources:\n{src}\n"
                f"last_verified: {now}\n---\n\n# {clean(entry.get('title', trip))}\n\n" + "\n".join(links) +
                f"\n\n## Actions\n{line}\n")
    page.write_text(text)
    return {"trip_page": str(page), "log": str(log)}
