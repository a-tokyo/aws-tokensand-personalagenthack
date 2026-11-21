"""Persona approver verification CLI for Marco (sandbox)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv

from services.audit import __main__ as audit

API_BASE = "https://api.withpersona.com/api/v1"
PERSONA_VERSION = "2023-01-05"
HOSTED_URL = "https://withpersona.com/verify?inquiry-id={}"
TIMEOUT = 15.0


class PersonaError(Exception):
    """A safe error that the CLI can print."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PersonaError("invalid_arguments", message)


def _headers() -> dict[str, str]:
    key = os.environ.get("PERSONA_API_KEY", "").strip()
    if not key:
        raise PersonaError("missing_config", "PERSONA_API_KEY is not set")
    return {
        "Authorization": f"Bearer {key}",
        "Persona-Version": PERSONA_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = httpx.request(
            method, f"{API_BASE}{path}", headers=_headers(), json=body, timeout=TIMEOUT
        )
    except httpx.HTTPError as exc:
        raise PersonaError("network_error", "could not reach Persona") from exc
    if response.status_code >= 400:
        raise PersonaError("persona_http_error", f"Persona returned HTTP {response.status_code}")
    return response.json()


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    inquiry_id = data.get("id")
    if not inquiry_id:
        raise PersonaError("bad_response", "Persona response has no inquiry id")
    status = (data.get("attributes") or {}).get("status")
    return {"inquiry_id": inquiry_id, "url": HOSTED_URL.format(inquiry_id), "status": status}


def _audit(trip_id: str, status: str, summary: str, inquiry_id: str, approver: str | None) -> None:
    audit.record(
        {
            "trip_id": trip_id,
            "act": "book",
            "step": "approval",
            "status": status,
            "summary": summary[:200],
            "sources": [{"type": "persona", "ref": inquiry_id, "quote": summary[:200]}],
            "external_ref": inquiry_id,
            "approved_by": approver,
        }
    )


def verify_approver(approver: str, trip_id: str) -> dict[str, Any]:
    template_id = os.environ.get("PERSONA_TEMPLATE_ID", "").strip()
    if not template_id:
        raise PersonaError("missing_config", "PERSONA_TEMPLATE_ID is not set")
    body = {
        "data": {
            "attributes": {
                "inquiry-template-id": template_id,
                "reference-id": f"marco-{trip_id}-{approver}",
            }
        }
    }
    result = _result(_request("POST", "/inquiries", body))
    _audit(
        trip_id,
        "proposed",
        f"Persona verification sent to approver {approver} (inquiry status {result['status']})",
        result["inquiry_id"],
        None,
    )
    return result


def inquiry_status(inquiry_id: str, trip_id: str | None = None) -> dict[str, Any]:
    payload = _request("GET", f"/inquiries/{inquiry_id}")
    result = _result(payload)
    attrs = (payload.get("data") or {}).get("attributes") or {}
    reference = attrs.get("reference-id") or ""
    # reference-id is "marco-<trip>-<approver>"; trip ids may hold hyphens, Slack ids do not.
    trip = trip_id or (
        reference.removeprefix("marco-").rsplit("-", 1)[0] if reference.startswith("marco-") else "unknown"
    )
    passed = result["status"] in {"completed", "approved"}
    failed = result["status"] in {"failed", "declined", "expired"}
    _audit(
        trip,
        "approved" if passed else "failed" if failed else "proposed",
        f"Persona inquiry status: {result['status']}",
        inquiry_id,
        None,
    )
    return result


def _parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(prog="python -m services.persona")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify-approver")
    verify.add_argument("--approver", required=True)
    verify.add_argument("--trip", required=True)
    status = sub.add_parser("status")
    status.add_argument("--inquiry", required=True)
    status.add_argument("--trip")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(audit.ROOT / ".env")
    try:
        args = _parser().parse_args(argv)
        if args.command == "verify-approver":
            result = verify_approver(args.approver, args.trip)
        else:
            result = inquiry_status(args.inquiry, args.trip)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (PersonaError, audit.AuditError) as exc:
        print(json.dumps({"error": exc.code, "detail": exc.detail}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    sys.exit(main())
