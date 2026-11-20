import json

import httpx
import pytest

from services.audit import __main__ as audit
from services.persona import __main__ as persona


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "DATA_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(audit, "_db_settings", lambda: None)
    monkeypatch.setattr(audit, "_log_analytics", lambda row: None)
    monkeypatch.setattr(persona, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("PERSONA_API_KEY", "test-key")
    monkeypatch.setenv("PERSONA_TEMPLATE_ID", "itmpl_test")


def _mock(monkeypatch, status_code, payload, calls):
    def fake(method, url, headers, json, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return httpx.Response(status_code, json=payload)

    monkeypatch.setattr(persona.httpx, "request", fake)


def _inquiry(status, ref="marco-t1-U123"):
    return {"data": {"id": "inq_abc", "attributes": {"status": status, "reference-id": ref}}}


def test_verify_approver_creates_inquiry_and_audits(monkeypatch, capsys):
    calls = []
    _mock(monkeypatch, 201, _inquiry("created"), calls)
    assert persona.main(["verify-approver", "--approver", "U123", "--trip", "t1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {
        "inquiry_id": "inq_abc",
        "url": "https://withpersona.com/verify?inquiry-id=inq_abc",
        "status": "created",
    }
    call = calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/api/v1/inquiries")
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["Persona-Version"] == persona.PERSONA_VERSION
    attrs = call["json"]["data"]["attributes"]
    assert attrs == {"inquiry-template-id": "itmpl_test", "reference-id": "marco-t1-U123"}
    rows = audit.list_rows("t1")
    assert len(rows) == 1
    assert rows[0]["step"] == "approval" and rows[0]["status"] == "proposed"
    assert rows[0]["sources"][0]["type"] == "persona"
    assert rows[0]["external_ref"] == "inq_abc"


@pytest.mark.parametrize(
    "remote,expected",
    [("completed", "approved"), ("approved", "approved"), ("declined", "failed"), ("pending", "proposed")],
)
def test_status_maps_and_audits(monkeypatch, capsys, remote, expected):
    calls = []
    _mock(monkeypatch, 200, _inquiry(remote), calls)
    assert persona.main(["status", "--inquiry", "inq_abc"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == remote
    assert calls[0]["method"] == "GET" and calls[0]["url"].endswith("/inquiries/inq_abc")
    rows = audit.list_rows("t1")
    assert rows[-1]["status"] == expected


def test_http_error_is_safe_and_not_audited(monkeypatch, capsys):
    _mock(monkeypatch, 401, {"errors": [{"title": "secret detail"}]}, [])
    assert persona.main(["verify-approver", "--approver", "U1", "--trip", "t1"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "persona_http_error"
    assert "secret" not in json.dumps(out)
    assert audit.list_rows("t1") == []


def test_missing_key(monkeypatch, capsys):
    monkeypatch.delenv("PERSONA_API_KEY")
    assert persona.main(["verify-approver", "--approver", "U1", "--trip", "t1"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "missing_config"
