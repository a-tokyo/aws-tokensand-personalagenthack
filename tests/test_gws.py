import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.gws import __main__ as g


def test_regex_extract_month_names():
    r = g.regex_extract("Workshop moved", "The workshop is postponed from Nov 30 - Dec 2 to Jan 12-14.")
    assert r["old_dates"]["start"].endswith("-11-30") and r["old_dates"]["end"].endswith("-12-02")
    assert r["new_dates"]["start"].endswith("-01-12") and r["new_dates"]["end"].endswith("-01-14")


def test_regex_extract_day_first_and_iso():
    r = g.regex_extract("Workshop rescheduled", "From 30 Nov to 2 Dec, now 2027-01-12 to 2027-01-14.")
    assert r["new_dates"] == {"start": "2027-01-12", "end": "2027-01-14"}
    assert r["old_dates"]["start"].endswith("-11-30")


def test_regex_extract_no_trigger_or_one_range():
    assert g.regex_extract("Lunch", "Meet Nov 30 - Dec 2 and Jan 12-14.") is None
    assert g.regex_extract("Workshop moved", "See you Nov 30 - Dec 2.") is None


def test_regex_extract_subject_only_uses_known_old_dates():
    old = {"start": "2026-11-30", "end": "2026-12-02"}
    r = g.regex_extract("Bart's AI workshop moved to Jan 12–14", "Hi Tokyo, see subject.", known_old=old)
    assert r["old_dates"] == old
    assert r["new_dates"]["start"].endswith("-01-12") and r["new_dates"]["end"].endswith("-01-14")


def test_regex_extract_subject_range_is_new_when_body_has_both():
    r = g.regex_extract("Bart's AI workshop moved to Jan 12–14", "It moves from Nov 30 - Dec 2 to Jan 12-14.")
    assert r["old_dates"]["start"].endswith("-11-30")
    assert r["new_dates"]["start"].endswith("-01-12")


ROWS = [
    {"id": "r1", "step": "perk_submit", "status": "done", "act": "book", "external_ref": "PERK1"},
    {"id": "r2", "step": "calendar", "status": "done", "act": "book", "external_ref": "ev1,ev2"},
    {"id": "r3", "step": "uber_schedule", "status": "done", "act": "book", "external_ref": "ride1"},
    {"id": "r4", "step": "ticket", "status": "done", "act": "book", "external_ref": "task1"},
    {"id": "r5", "step": "perk_cancel", "status": "failed", "act": "book", "external_ref": None},
]
CHANGE = {"old_dates": {"start": "2026-11-30", "end": "2026-12-02"},
          "new_dates": {"start": "2027-01-12", "end": "2027-01-14"}}


def test_replan_actions():
    out = g.build_replan("novato-2026-11-30", CHANGE, ROWS)
    steps = [a["step"] for a in out["actions"]]
    assert steps == ["perk_cancel", "perk_fill", "calendar", "uber_cancel", "uber_schedule",
                     "ticket", "email_draft", "email_draft"]
    by = {a["step"]: a for a in out["actions"]}
    assert by["perk_cancel"]["args"]["perk_trip"] == "PERK1" and by["perk_cancel"]["supersedes"] == "r1"
    assert by["calendar"]["args"]["event_ids"] == ["ev1", "ev2"]
    assert by["calendar"]["args"]["start"] == "2027-01-12"
    assert by["ticket"]["args"]["due"] == "2027-01-12"
    assert all(a["supersedes"] for a in out["actions"])
    assert "Nothing runs until Tokyo approves" in out["proposal"]


def test_replan_skips_already_superseded():
    rows = ROWS + [{"id": "r6", "step": "calendar", "status": "done", "act": "replan",
                    "external_ref": "ev9", "supersedes": "r2"}]
    out = g.build_replan("t", CHANGE, rows)
    cal = [a for a in out["actions"] if a["step"] == "calendar"]
    assert len(cal) == 0  # r2 superseded; replan rows are not re-planned
