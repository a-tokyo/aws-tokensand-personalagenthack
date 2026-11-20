import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.audit import __main__ as audit


def _payload(trip_id: str, summary: str) -> dict:
    return {
        "trip_id": trip_id,
        "act": "book",
        "step": "recall",
        "status": "done",
        "summary": summary,
        "sources": [
            {
                "type": "kb",
                "ref": "kb/trips/novato.md",
                "quote": "Use the Courtyard in Novato.",
            }
        ],
        "model": None,
        "cost_usd": 0.0,
        "external_ref": None,
        "supersedes": None,
        "approved_by": None,
    }


@pytest.fixture(autouse=True)
def local_only(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DATA_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(audit, "_db_settings", lambda: None)
    monkeypatch.setattr(audit, "_log_analytics", lambda row: None)


def test_record_and_list_use_jsonl_fallback():
    first = audit.record(_payload("novato-2027-01-12", "Recalled the Novato hotel."))
    audit.record(_payload("dublin-2027-02-01", "Recalled the Dublin hotel."))

    rows = audit.list_rows("novato-2027-01-12")

    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["trip_id"] == "novato-2027-01-12"
    assert rows[0]["sources"][0]["type"] == "kb"

    mirror_rows = [
        json.loads(line) for line in audit.DATA_PATH.read_text(encoding="utf-8").splitlines()
    ]
    assert len(mirror_rows) == 2


def test_connection_failure_uses_jsonl_fallback(monkeypatch):
    monkeypatch.setattr(
        audit,
        "_db_settings",
        lambda: {"host": "db", "user": "user", "password": "secret", "database": "marco"},
    )

    def connection_failure(settings):
        raise OSError("database is unavailable")

    monkeypatch.setattr(audit, "_connect_db", connection_failure)

    saved = audit.record(_payload("novato-2027-01-12", "Recalled the Novato hotel."))

    assert audit.list_rows("novato-2027-01-12")[0]["id"] == saved["id"]


def test_export_groups_all_rows_by_trip(tmp_path):
    audit.record(_payload("novato-2027-01-12", "Recalled the hotel."))
    audit.record(_payload("novato-2027-01-12", "Recalled the flight."))
    audit.record(_payload("dublin-2027-02-01", "Recalled the hotel."))
    output = tmp_path / "web" / "audit.json"

    grouped = audit.export_rows(output)
    document = json.loads(output.read_text(encoding="utf-8"))

    assert set(grouped) == {"novato-2027-01-12", "dublin-2027-02-01"}
    assert len(document["trips"]["novato-2027-01-12"]) == 2
    assert len(document["trips"]["dublin-2027-02-01"]) == 1


def test_record_many_writes_all_rows_in_order():
    rows = audit.record_many([
        _payload("novato-2027-01-12", "Recalled the Novato hotel."),
        {**_payload("novato-2027-01-12", "Checked the policy."), "step": "policy"},
    ])

    listed = audit.list_rows("novato-2027-01-12")
    assert [r["id"] for r in listed] == [r["id"] for r in rows]
    assert [r["step"] for r in listed] == ["recall", "policy"]


def test_record_many_writes_nothing_when_one_row_is_invalid():
    bad = {**_payload("novato-2027-01-12", "Bad row."), "step": "not-a-step"}

    with pytest.raises(audit.AuditError):
        audit.record_many([_payload("novato-2027-01-12", "Good row."), bad])

    assert audit.list_rows("novato-2027-01-12") == []
