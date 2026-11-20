"""Audit storage and analytics CLI for Marco."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "audit.jsonl"

ACTS = {"book", "replan", "brief", "other"}
STEPS = {
    "recall",
    "policy",
    "rank",
    "perk_fill",
    "perk_submit",
    "perk_cancel",
    "uber_schedule",
    "uber_cancel",
    "calendar",
    "email_draft",
    "ticket",
    "kb_write",
    "notify",
    "approval",
}
STATUSES = {"proposed", "approved", "done", "failed", "cancelled"}
SOURCE_TYPES = {"cognee", "kb", "senso", "gmail", "slack", "calendar", "perk", "web"}
ROW_COLUMNS = (
    "id",
    "ts",
    "trip_id",
    "act",
    "step",
    "status",
    "summary",
    "sources",
    "model",
    "cost_usd",
    "external_ref",
    "supersedes",
    "approved_by",
)


class AuditError(Exception):
    """A safe error that can be returned by the CLI."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AuditError("invalid_arguments", message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_text(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise AuditError("invalid_row", f"{name} must be a non-empty string")
    return value.strip()


def _optional_text(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AuditError("invalid_row", f"{name} must be a string or null")
    return value


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    trip_id = _required_text(payload, "trip_id")
    act = _required_text(payload, "act")
    step = _required_text(payload, "step")
    status = _required_text(payload, "status")
    summary = _required_text(payload, "summary")

    if act not in ACTS:
        raise AuditError("invalid_row", "act is not in the audit contract")
    if step not in STEPS:
        raise AuditError("invalid_row", "step is not in the audit contract")
    if status not in STATUSES:
        raise AuditError("invalid_row", "status is not in the audit contract")
    if len(summary) > 200:
        raise AuditError("invalid_row", "summary must contain at most 200 characters")

    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        raise AuditError("invalid_row", "sources must be a list")
    clean_sources = []
    for source in sources:
        if not isinstance(source, dict):
            raise AuditError("invalid_row", "each source must be an object")
        source_type = _required_text(source, "type")
        source_ref = _required_text(source, "ref")
        quote = _required_text(source, "quote")
        if source_type not in SOURCE_TYPES:
            raise AuditError("invalid_row", "source type is not in the audit contract")
        if len(quote) > 200:
            raise AuditError("invalid_row", "source quote must contain at most 200 characters")
        clean_sources.append({"type": source_type, "ref": source_ref, "quote": quote})

    cost = payload.get("cost_usd", 0.0)
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        raise AuditError("invalid_row", "cost_usd must be a non-negative number")

    return {
        "trip_id": trip_id,
        "act": act,
        "step": step,
        "status": status,
        "summary": summary,
        "sources": clean_sources,
        "model": _optional_text(payload, "model"),
        "cost_usd": float(cost),
        "external_ref": _optional_text(payload, "external_ref"),
        "supersedes": _optional_text(payload, "supersedes"),
        "approved_by": _optional_text(payload, "approved_by"),
    }


def _append_local(row: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with DATA_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    except OSError as exc:
        raise AuditError("local_write_failed", "could not write the local audit mirror") from exc


def _read_local() -> list[dict[str, Any]]:
    if not DATA_PATH.exists():
        return []
    rows = []
    try:
        with DATA_PATH.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AuditError(
                        "local_data_invalid", f"invalid JSON on audit mirror line {line_number}"
                    ) from exc
                if not isinstance(value, dict):
                    raise AuditError(
                        "local_data_invalid", f"invalid row on audit mirror line {line_number}"
                    )
                rows.append(value)
    except OSError as exc:
        raise AuditError("local_read_failed", "could not read the local audit mirror") from exc
    return rows


def _db_settings() -> dict[str, Any] | None:
    required = {
        "host": os.getenv("SINGLESTORE_HOST"),
        "user": os.getenv("SINGLESTORE_USER"),
        "password": os.getenv("SINGLESTORE_PASSWORD"),
        "database": os.getenv("SINGLESTORE_DATABASE"),
    }
    if not all(required.values()):
        return None
    try:
        port = int(os.getenv("SINGLESTORE_PORT", "3306"))
    except ValueError:
        return None
    return {**required, "port": port}


def _connect_db(settings: dict[str, Any]) -> Any:
    import singlestoredb

    return singlestoredb.connect(
        **settings,
        autocommit=True,
        connect_timeout=2,
        parse_json=False,
    )


def _ensure_table(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id CHAR(36) NOT NULL,
            ts VARCHAR(40) NOT NULL,
            trip_id VARCHAR(255) NOT NULL,
            act VARCHAR(32) NOT NULL,
            step VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL,
            summary VARCHAR(200) NOT NULL,
            sources JSON NOT NULL,
            model VARCHAR(255),
            cost_usd DOUBLE NOT NULL DEFAULT 0,
            external_ref VARCHAR(255),
            supersedes CHAR(36),
            approved_by VARCHAR(255),
            PRIMARY KEY (id),
            KEY trip_ts (trip_id, ts)
        )
        """
    )


def _try_db_insert(row: dict[str, Any]) -> bool:
    settings = _db_settings()
    if settings is None:
        return False
    connection = None
    cursor = None
    try:
        connection = _connect_db(settings)
        cursor = connection.cursor()
        _ensure_table(cursor)
        cursor.execute(
            """
            INSERT INTO decisions (
                id, ts, trip_id, act, step, status, summary, sources, model,
                cost_usd, external_ref, supersedes, approved_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row["id"],
                row["ts"],
                row["trip_id"],
                row["act"],
                row["step"],
                row["status"],
                row["summary"],
                json.dumps(row["sources"], separators=(",", ":"), ensure_ascii=False),
                row["model"],
                row["cost_usd"],
                row["external_ref"],
                row["supersedes"],
                row["approved_by"],
            ),
        )
        return True
    except Exception:
        return False
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _normalise_db_row(values: tuple[Any, ...]) -> dict[str, Any]:
    row = dict(zip(ROW_COLUMNS, values, strict=True))
    sources = row["sources"]
    if isinstance(sources, (bytes, bytearray)):
        sources = sources.decode("utf-8")
    if isinstance(sources, str):
        sources = json.loads(sources)
    row["sources"] = sources
    row["cost_usd"] = float(row["cost_usd"] or 0)
    return row


def _try_db_list(trip_id: str | None) -> list[dict[str, Any]] | None:
    settings = _db_settings()
    if settings is None:
        return None
    connection = None
    cursor = None
    try:
        connection = _connect_db(settings)
        cursor = connection.cursor()
        _ensure_table(cursor)
        columns = ", ".join(ROW_COLUMNS)
        if trip_id is None:
            cursor.execute(f"SELECT {columns} FROM decisions ORDER BY ts, id")
        else:
            cursor.execute(
                f"SELECT {columns} FROM decisions WHERE trip_id = %s ORDER BY ts, id",
                (trip_id,),
            )
        return [_normalise_db_row(tuple(values)) for values in cursor.fetchall()]
    except Exception:
        return None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def list_rows(trip_id: str | None = None) -> list[dict[str, Any]]:
    local_rows = _read_local()
    if trip_id is not None:
        local_rows = [row for row in local_rows if row.get("trip_id") == trip_id]
    db_rows = _try_db_list(trip_id)
    if db_rows is not None:
        rows_by_id = {str(row.get("id")): row for row in local_rows}
        rows_by_id.update({str(row.get("id")): row for row in db_rows})
        local_rows = list(rows_by_id.values())
    return sorted(local_rows, key=lambda row: (str(row.get("ts", "")), str(row.get("id", ""))))


def _wait_for_statsig(operation: Any, timeout: float = 1.0) -> None:
    wait = getattr(operation, "wait", None)
    if callable(wait):
        wait(timeout)


def _statsig_client() -> Any | None:
    secret = os.getenv("STATSIG_SERVER_SECRET")
    if not secret:
        return None
    try:
        from statsig_python_core import Statsig, StatsigOptions

        client = Statsig(
            secret,
            StatsigOptions(
                init_timeout_ms=1000,
                event_logging_flush_interval_ms=500,
                disable_disk_access=True,
            ),
        )
        _wait_for_statsig(client.initialize())
        return client
    except Exception:
        return None


def _close_statsig(client: Any) -> None:
    try:
        _wait_for_statsig(client.flush_events())
    except Exception:
        pass
    try:
        _wait_for_statsig(client.shutdown())
    except Exception:
        pass


def _log_statsig(row: dict[str, Any], event_name: str) -> None:
    client = _statsig_client()
    if client is None:
        return
    try:
        from statsig_python_core import StatsigUser

        metadata = {
            "step": row["step"],
            "trip": row["trip_id"],
            "model": row["model"] or "",
            "cost": str(row["cost_usd"]),
        }
        client.log_event(
            StatsigUser(user_id="tokyo"),
            event_name,
            value=row["cost_usd"],
            metadata=metadata,
        )
    except Exception:
        pass
    finally:
        _close_statsig(client)


def _log_amplitude(row: dict[str, Any], event_name: str) -> None:
    api_key = os.getenv("AMPLITUDE_API_KEY")
    if not api_key:
        return
    client = None
    try:
        from amplitude import Amplitude, BaseEvent, Config

        client = Amplitude(
            api_key,
            Config(flush_queue_size=1, flush_interval_millis=500, flush_max_retries=0),
        )
        client.track(
            BaseEvent(
                event_type=event_name,
                user_id="tokyo",
                event_properties={
                    "step": row["step"],
                    "trip": row["trip_id"],
                    "model": row["model"],
                    "cost": row["cost_usd"],
                },
            )
        )
        for future in client.flush():
            try:
                future.result(timeout=1)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                pass


def _log_analytics(row: dict[str, Any]) -> None:
    event_name = f"marco_{row['step']}_{row['status']}"
    _log_statsig(row, event_name)
    _log_amplitude(row, event_name)


def record(payload: dict[str, Any]) -> dict[str, Any]:
    clean = _validate_payload(payload)
    row = {
        "id": str(uuid.uuid4()),
        "ts": _utc_now(),
        **clean,
    }
    _append_local(row)
    _try_db_insert(row)
    _log_analytics(row)
    return row


def record_many(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate every row first, then record each. One bad row writes nothing."""
    if not isinstance(payloads, list) or not payloads:
        raise AuditError("invalid_json", "the JSON payload must be a non-empty array")
    for payload in payloads:
        if not isinstance(payload, dict):
            raise AuditError("invalid_json", "each row must be an object")
        _validate_payload(payload)
    return [record(payload) for payload in payloads]


def check_gate(name: str) -> bool:
    client = _statsig_client()
    if client is None:
        return False
    try:
        from statsig_python_core import StatsigUser

        return bool(client.check_gate(StatsigUser(user_id="tokyo"), name))
    except Exception:
        return False
    finally:
        _close_statsig(client)


def export_rows(out_path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in list_rows():
        grouped.setdefault(str(row.get("trip_id", "")), []).append(row)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_text(
            json.dumps({"trips": grouped}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise AuditError("export_failed", "could not write the audit export") from exc
    return grouped


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuditError("invalid_json", "the JSON payload is invalid") from exc
    if not isinstance(value, dict):
        raise AuditError("invalid_json", "the JSON payload must be an object")
    return value


def _parser() -> JsonArgumentParser:
    parser = JsonArgumentParser(prog="python -m services.audit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("--json", dest="json_payload", required=True)

    many_parser = subparsers.add_parser("record-many")
    many_parser.add_argument("--json", dest="json_payload", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--trip", required=True)

    gate_parser = subparsers.add_parser("gate")
    gate_parser.add_argument("--name", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    try:
        args = _parser().parse_args(argv)
        if args.command == "record":
            result = {"id": record(_json_object(args.json_payload))["id"]}
        elif args.command == "record-many":
            try:
                rows = json.loads(args.json_payload)
            except json.JSONDecodeError as exc:
                raise AuditError("invalid_json", "the JSON payload is invalid") from exc
            result = {"ids": [row["id"] for row in record_many(rows)]}
        elif args.command == "list":
            result = {"rows": list_rows(args.trip)}
        elif args.command == "gate":
            result = {"enabled": check_gate(args.name)}
        else:
            grouped = export_rows(Path(args.out))
            result = {"out": args.out, "trips": len(grouped)}
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        return 0
    except AuditError as exc:
        print(
            json.dumps(
                {"error": exc.code, "detail": exc.detail},
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
        return 1
    except Exception:
        print('{"error":"internal_error","detail":"audit command failed"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
