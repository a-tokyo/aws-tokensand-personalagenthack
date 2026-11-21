import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import marco_ops as ops  # noqa: E402

NOVATO = {"trip_id": "novato-2k-workshop-2026-11", "place": "Novato", "traveller": "Tokyo",
          "dates": {"start": "2026-11-30", "end": "2026-12-04"}, "perk_draft": {"perk_trip_id": "<perk-trip-id>"}}


def test_require_owner_accepts_only_the_owner_id(monkeypatch):
    monkeypatch.setenv("SLACK_OWNER_ID", "U_OWNER")
    ops.require_owner("U_OWNER")
    for sender in ("U_OTHER", "", "Tokyo"):
        with pytest.raises(ops.NotOwner):
            ops.require_owner(sender)


def test_require_owner_fails_closed_without_owner(monkeypatch):
    monkeypatch.setattr(ops, "owner_id", lambda: "")
    with pytest.raises(ops.NotOwner):
        ops.require_owner("U_OWNER")


def test_find_clashes_flags_overlap_only():
    assert ops.find_clashes("2026-12-01", "2026-12-03", [NOVATO])[0]["trip_id"] == NOVATO["trip_id"]
    assert ops.find_clashes("2026-12-05", "2026-12-07", [NOVATO]) == []
    assert ops.find_clashes("2026-12-04", "2026-12-04", [NOVATO])  # same-day edge counts


def test_cancel_apply_refuses_non_owner(monkeypatch):
    monkeypatch.setenv("SLACK_OWNER_ID", "U_OWNER")
    rc = ops.main(["cancel-apply", "--approved-by", "U_OTHER"])
    assert rc == 1


def test_same_place_is_the_existing_trip_not_a_clash():
    assert ops.find_clashes("2026-11-30", "2026-12-02", [NOVATO], "Novato") == []
    assert ops.find_same_trip("2026-11-30", "2026-12-02", [NOVATO], "Novato, CA")["trip_id"] == NOVATO["trip_id"]
    assert ops.find_clashes("2026-12-01", "2026-12-03", [NOVATO], "Austin")


def _state():
    return {
        "trip_id": "test-trip", "place": "Novato, CA", "dates": {"start": "2026-11-30", "end": "2026-12-04"},
        "event_dates": {"start": "2026-11-30", "end": "2026-12-02"},
        "perk_draft": {"perk_trip_id": "1", "status": "draft", "checkout_total_eur": 10.0},
        "hotel_info": {"name": "H", "address": "A", "check_in": "15:00", "check_out": "11:00", "room": "King",
                       "breakfast": "Room only.", "nights": "4 nights", "image_url": "https://x/i.jpg"},
        "flights": [{"leg": "Out", "depart": "2026-11-30T05:00", "depart_tz": "Europe/Lisbon", "arrive": "2026-11-30T11:45",
                     "arrive_tz": "America/Los_Angeles", "from": "OPO", "to": "SFO", "via": "AMS", "airline": "KLM",
                     "flight_no": "KL1", "cabin": "Economy"}],
        "ground": [{"product": "UberX", "when": "Fri 4 Dec 2026 05:30 PST", "pickup": "Hotel", "expense_code": "2K",
                    "cancel": "free up to 60 minutes before pickup", "reservation_id": "r1"}],
    }


def test_itinerary_blocks_have_header_image_and_audit_footer():
    import marco_itinerary as it
    blocks = it.build_blocks(_state(), "U1", 7, "Done.")
    assert blocks[0]["text"]["text"] == "✈️ Novato · Mon 30 Nov – Fri 4 Dec"
    assert any(b["type"] == "image" and b["alt_text"] for b in blocks)
    assert "Audit trail: 7 steps" in blocks[-1]["elements"][0]["text"]
    assert "Check in online from Sun 29 Nov 05:00" in str(blocks)


def test_itinerary_ask_follows_state():
    import marco_itinerary as it
    st = _state()
    assert "approve submit" in it.build_blocks(st, "U1", 0)[2]["text"]["text"]
    st["perk_draft"]["status"] = "submitted, approved"
    assert "Approved" in it.build_blocks(st, "U1", 0)[2]["text"]["text"]
    st["cancelled"] = True
    blocks = it.build_blocks(st, "U1", 0)
    assert "Cancelled" in blocks[2]["text"]["text"]
    assert not any(b["type"] == "actions" for b in blocks)


def test_calendar_events_are_per_item():
    import marco_approve as ap
    titles = [e["title"] for e in ap.calendar_events(_state())]
    assert titles == ["Flight OPO-SFO KL1", "Hotel: H", "2K AI workshop (Bart), Novato", "Uber to SFO"]


def test_approve_is_idempotent_per_thread_and_option(tmp_path, monkeypatch, capsys):
    import marco_approve as ap
    monkeypatch.setenv("SLACK_OWNER_ID", "U_OWNER")
    monkeypatch.setattr(ap, "ROOT", tmp_path)
    marker = tmp_path / "data" / "approve_done" / "123.4_A.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"trip_id": "test-trip", "calendar": {"event_ids": ["e1"]}, "ticket": {"task_id": "t1"}}')
    calls = []
    monkeypatch.setattr(ap, "cli", lambda *a: calls.append(a) or {"exists": True})
    assert ap.main(["--trip", "test-trip", "--option", "A", "--approved-by", "U_OWNER", "--thread-ts", "123.4"]) == 0
    assert '"already_done": true' in capsys.readouterr().out
    assert all(c[1] == "exists" for c in calls)  # only existence checks, no writes


def test_state_replan_lists_every_action():
    st = {**_state(), "calendar_event_ids": ["e1", "e2", "e3", "e4", "e5"], "task_id": "t1"}
    change = {"old_dates": {"start": "2026-11-30", "end": "2026-12-02"}, "new_dates": {"start": "2027-01-12", "end": "2027-01-14"}}
    plan = ops.state_replan(st, change)
    steps = [a["step"] for a in plan["actions"]]
    assert steps == ["calendar", "ticket", "perk_fill", "uber_cancel", "uber_schedule", "email_draft", "email_draft"]
    cal = plan["actions"][0]["args"]
    assert cal["shift_days"] == 43 and cal["event_ids"] == ["e1", "e2", "e3", "e4", "e5"]
    perk = plan["actions"][2]["args"]
    assert (perk["hotel_in"], perk["hotel_out"]) == ("2027-01-11", "2027-01-15")


def test_state_replan_without_ids_still_lists_actions():
    change = {"old_dates": {"start": "2026-11-30", "end": "2026-12-02"}, "new_dates": {"start": "2027-01-12", "end": "2027-01-14"}}
    assert len(ops.state_replan(_state(), change)["actions"]) >= 6


def test_approve_reruns_when_items_were_deleted(tmp_path, monkeypatch):
    import marco_approve as ap
    monkeypatch.setattr(ap, "cli", lambda *a: {"exists": False})
    assert ap.items_exist({"calendar": {"event_ids": ["e1"]}, "ticket": {"task_id": "t1"}}) is False
    monkeypatch.setattr(ap, "cli", lambda *a: {"exists": True})
    assert ap.items_exist({"calendar": {"event_ids": ["e1"]}, "ticket": {"task_id": "t1"}}) is True
    assert ap.items_exist({"calendar": {"event_ids": []}}) is False


@pytest.mark.parametrize("text,kind", [
    ("Heads up: Bart's workshop moved to Jan 12-14.", "moved"),
    ("The Novato workshop is postponed to January.", "moved"),
    ("Ana will go instead of Tokyo to Novato.", "swap"),
    ("The 2K workshop is cancelled.", "cancelled"),
    ("Can Tokyo join the Austin hackathon, Dec 1-3?", "new_trip"),
    ("lol nice, lunch at 1?", "none"),
    ("Thanks Marco!", "none"),
    ("I moved the meeting notes to Drive.", "none"),
])
def test_detect_change(text, kind):
    assert ops.detect_change(text, ["Novato, CA"])["change"] == kind


def test_room_check_gate_off_skips_classifier():
    r = ops.room_check("The Novato workshop moved to Jan 12-14.", ["Novato, CA"], gate=lambda n: False)
    assert r == {"act": False, "gate": "proactive_mode=off", "change": "skipped"}


def test_room_check_gate_on_acts_only_on_trip_change():
    on = lambda n: True
    assert ops.room_check("The Novato workshop moved to Jan 12-14.", ["Novato, CA"], gate=on) == \
        {"act": True, "gate": "proactive_mode=on", "change": "moved"}
    assert ops.room_check("lunch at 1?", ["Novato, CA"], gate=on)["act"] is False


def test_gate_is_cached_for_a_minute(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "DATA", tmp_path)
    calls = []
    monkeypatch.setattr(ops, "cli", lambda *a: calls.append(a) or {"enabled": True})
    assert ops.gate_on(now=1000.0) is True
    assert ops.gate_on(now=1030.0) is True
    assert len(calls) == 1
    ops.gate_on(now=1100.0)
    assert len(calls) == 2


def _approve_env(tmp_path, monkeypatch, state, persona_status):
    import marco_approve as ap
    monkeypatch.setenv("SLACK_OWNER_ID", "U_OWNER")
    monkeypatch.setattr(ap, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trip_novato.json").write_text(json.dumps(state))
    calls = []

    def fake(module, *args):
        calls.append((module, *args))
        if module == "services.persona":
            return {"inquiry_id": "inq_1", "url": "https://withpersona.com/verify?inquiry-id=inq_1", "status": persona_status}
        if args[:1] == ("calendar-event",):
            return {"event_ids": ["e"]}
        if args[:1] == ("ticket",):
            return {"task_id": "t1"}
        return {"id": "r", "rows": []}

    monkeypatch.setattr(ap, "cli", fake)
    return ap, calls


def _st(**extra):
    st = _state()
    st["perk_draft"].update({"itinerary_url": "https://perk/x"})
    return {**st, **extra}


def test_submit_holds_until_persona_verified(tmp_path, monkeypatch, capsys):
    ap, calls = _approve_env(tmp_path, monkeypatch, _st(), "created")
    assert ap.main(["--trip", "test-trip", "--option", "A", "--approved-by", "U_OWNER", "--submit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert ("services.persona", "verify-approver", "--approver", "U_OWNER", "--trip", "test-trip") in calls
    assert out["persona"]["url"].endswith("inq_1")
    assert not any(t["step"] == "perk_submit" for t in out["browser_todo"])
    assert "held until verified" in out["held"][0]["text"]
    saved = json.loads((tmp_path / "data" / "trip_novato.json").read_text())
    assert saved["persona"]["inquiry_id"] == "inq_1" and saved["persona"]["approver"] == "U_OWNER"


def test_submit_goes_ahead_when_persona_completed(tmp_path, monkeypatch, capsys):
    prev = {"inquiry_id": "inq_1", "url": "u", "status": "pending", "approver": "U_OWNER"}
    ap, calls = _approve_env(tmp_path, monkeypatch, _st(persona=prev), "completed")
    assert ap.main(["--trip", "test-trip", "--option", "A", "--approved-by", "U_OWNER", "--submit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert ("services.persona", "status", "--inquiry", "inq_1", "--trip", "test-trip") in calls
    assert not any(c[1] == "verify-approver" for c in calls if c[0] == "services.persona")
    assert any(t["step"] == "perk_submit" for t in out["browser_todo"])


def test_plain_approve_skips_persona(tmp_path, monkeypatch, capsys):
    ap, calls = _approve_env(tmp_path, monkeypatch, _st(), "created")
    assert ap.main(["--trip", "test-trip", "--option", "A", "--approved-by", "U_OWNER"]) == 0
    assert not any(c[0] == "services.persona" for c in calls)


def test_demo_mode_shows_link_and_holds_submit(tmp_path, monkeypatch, capsys):
    import marco_itinerary as it
    ap, calls = _approve_env(tmp_path, monkeypatch, _st(demo_mode=True), "created")
    assert ap.main(["--trip", "test-trip", "--option", "A", "--approved-by", "U_OWNER"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert any(c[0] == "services.persona" for c in calls)
    assert out["browser_todo"] == []
    assert any(h["step"] == "perk_submit" and "held until verified" in h["text"] for h in out["held"])
    saved = json.loads((tmp_path / "data" / "trip_novato.json").read_text())
    buttons = [e for b in it.build_blocks(saved, "U1", 0) if b["type"] == "actions" for e in b["elements"]]
    assert any(e["text"]["text"] == "🪪 Verify it's you (Persona)" and e["url"].endswith("inq_1") for e in buttons)
    saved["persona"]["status"] = "approved"
    buttons = [e for b in it.build_blocks(saved, "U1", 0) if b["type"] == "actions" for e in b["elements"]]
    assert not any(e["action_id"] == "persona_verify" for e in buttons)


def test_done_card_has_persona_button():
    import marco_card as mc
    blocks = mc.done_blocks({"trip": "t", "items": [], "persona_url": "https://withpersona.com/verify?inquiry-id=i"})
    el = [b for b in blocks if b["type"] == "actions"][0]["elements"][0]
    assert el["url"].endswith("=i") and "Persona" in el["text"]["text"]
