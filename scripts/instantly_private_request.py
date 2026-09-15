from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

COMMAND_SHEET = "InstantlyCommands"
RESULT_SHEET = "InstantlyResults"
COMMAND_HEADERS = [
    "request_id",
    "status",
    "method",
    "path",
    "query_json",
    "body_json",
    "apply",
    "confirmation",
    "verify_json",
    "note",
    "result_status",
    "result_summary",
]
RESULT_HEADERS = [
    "request_id",
    "recorded_at",
    "status",
    "method",
    "path",
    "risk",
    "applied",
    "response_json",
    "verification_json",
]
SAFE_REQUEST_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")
MAX_CELL_CHARS = 45_000


class PrivateRequestError(RuntimeError):
    pass


def _require_request_id(value: str) -> str:
    request_id = (value or "").strip()
    if not request_id or len(request_id) > 160 or any(ch not in SAFE_REQUEST_ID_CHARS for ch in request_id):
        raise PrivateRequestError("invalid request_id")
    return request_id


def _load_service(*, readonly: bool):
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise PrivateRequestError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PrivateRequestError("GOOGLE_SERVICE_ACCOUNT_JSON is invalid") from exc
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scope = (
        "https://www.googleapis.com/auth/spreadsheets.readonly"
        if readonly
        else "https://www.googleapis.com/auth/spreadsheets"
    )
    credentials = service_account.Credentials.from_service_account_info(info, scopes=[scope])
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _spreadsheet_id() -> str:
    value = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
    if not value:
        raise PrivateRequestError("OUTREACH_SPREADSHEET_ID is required")
    return value


def _metadata(service, spreadsheet_id: str) -> dict[str, int]:
    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties"
    ).execute()
    return {
        str(item["properties"]["title"]): int(item["properties"]["sheetId"])
        for item in response.get("sheets", [])
    }


def _get_values(service, spreadsheet_id: str, range_name: str) -> list[list[str]]:
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_name
    ).execute()
    return response.get("values", [])


def _ensure_sheet(service, spreadsheet_id: str, title: str, headers: list[str]) -> None:
    sheets = _metadata(service, spreadsheet_id)
    if title not in sheets:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
    values = _get_values(service, spreadsheet_id, f"'{title}'!1:1")
    existing = [str(v).strip() for v in values[0]] if values else []
    if not existing:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{title}'!A1",
            valueInputOption="RAW",
            body={"values": [headers]},
        ).execute()
    elif existing != headers:
        raise PrivateRequestError(f"{title} headers do not match the required contract")


def bootstrap() -> dict[str, Any]:
    service = _load_service(readonly=False)
    spreadsheet_id = _spreadsheet_id()
    _ensure_sheet(service, spreadsheet_id, COMMAND_SHEET, COMMAND_HEADERS)
    _ensure_sheet(service, spreadsheet_id, RESULT_SHEET, RESULT_HEADERS)
    return {"status": "green", "sheets": [COMMAND_SHEET, RESULT_SHEET]}


def _rows(values: list[list[str]]) -> list[dict[str, str]]:
    if not values:
        return []
    headers = [str(value).strip() for value in values[0]]
    rows: list[dict[str, str]] = []
    for raw in values[1:]:
        padded = list(raw) + [""] * max(0, len(headers) - len(raw))
        rows.append({headers[index]: str(padded[index]) for index in range(len(headers))})
    return rows


def _json_field(value: str, field: str, *, default: Any) -> Any:
    text = (value or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PrivateRequestError(f"{field} is invalid JSON") from exc


def load_request(request_id: str) -> dict[str, Any]:
    request_id = _require_request_id(request_id)
    service = _load_service(readonly=True)
    spreadsheet_id = _spreadsheet_id()
    rows = _rows(_get_values(service, spreadsheet_id, f"'{COMMAND_SHEET}'!A:L"))
    matches = [row for row in rows if row.get("request_id", "").strip() == request_id]
    if len(matches) != 1:
        raise PrivateRequestError(f"expected exactly one private request row; found {len(matches)}")
    row = matches[0]
    status = row.get("status", "").strip().lower()
    if status not in {"ready", "approved"}:
        raise PrivateRequestError("request status must be ready or approved")
    method = row.get("method", "").strip().upper()
    path = row.get("path", "").strip()
    if not method or not path:
        raise PrivateRequestError("method and path are required")
    apply_text = row.get("apply", "").strip().lower()
    if apply_text not in {"", "false", "true"}:
        raise PrivateRequestError("apply must be true or false")
    request: dict[str, Any] = {
        "method": method,
        "path": path,
        "query": _json_field(row.get("query_json", ""), "query_json", default={}),
        "body": _json_field(row.get("body_json", ""), "body_json", default=None),
        "apply": apply_text == "true",
        "confirmation": row.get("confirmation", "").strip(),
        "verify": _json_field(row.get("verify_json", ""), "verify_json", default=None),
    }
    if request["query"] is not None and not isinstance(request["query"], Mapping):
        raise PrivateRequestError("query_json must be an object")
    if request["verify"] is not None and not isinstance(request["verify"], Mapping):
        raise PrivateRequestError("verify_json must be an object")
    return request


def _clip_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(text) > MAX_CELL_CHARS:
        return text[: MAX_CELL_CHARS - 100] + '...[TRUNCATED: request a smaller page/range]'
    return text


def record_result(request_id: str, public_result: Mapping[str, Any], private_result: Mapping[str, Any]) -> dict[str, Any]:
    request_id = _require_request_id(request_id)
    service = _load_service(readonly=False)
    spreadsheet_id = _spreadsheet_id()
    _ensure_sheet(service, spreadsheet_id, COMMAND_SHEET, COMMAND_HEADERS)
    _ensure_sheet(service, spreadsheet_id, RESULT_SHEET, RESULT_HEADERS)

    values = _get_values(service, spreadsheet_id, f"'{COMMAND_SHEET}'!A:L")
    rows = _rows(values)
    match_indexes = [index for index, row in enumerate(rows, start=2) if row.get("request_id", "").strip() == request_id]
    if len(match_indexes) != 1:
        raise PrivateRequestError(f"expected exactly one private request row for result; found {len(match_indexes)}")
    row_number = match_indexes[0]
    status = str(public_result.get("status") or "unknown")
    summary = _clip_json({
        "status": status,
        "risk": public_result.get("risk"),
        "applied": public_result.get("applied"),
        "method": public_result.get("method"),
        "path": public_result.get("path"),
        "operation_id": public_result.get("operation_id"),
        "confirmation_token": public_result.get("confirmation_token"),
        "response_status": public_result.get("response_status"),
        "response_shape": public_result.get("response_shape"),
        "response_count": public_result.get("response_count"),
        "verification_status": public_result.get("verification_status"),
    })
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{COMMAND_SHEET}'!K{row_number}:L{row_number}",
        valueInputOption="RAW",
        body={"values": [[status, summary]]},
    ).execute()

    meta = private_result.get("meta") if isinstance(private_result.get("meta"), Mapping) else public_result
    response = private_result.get("response")
    verification = private_result.get("verification")
    result_row = [
        request_id,
        datetime.now(timezone.utc).isoformat(),
        status,
        str(meta.get("method") or ""),
        str(meta.get("path") or ""),
        str(meta.get("risk") or ""),
        str(bool(meta.get("applied", False))).lower(),
        _clip_json(response),
        _clip_json(verification),
    ]
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"'{RESULT_SHEET}'!A:I",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [result_row]},
    ).execute()
    return {"status": "green", "request_id": request_id, "private_result_recorded": True}


def _write_json(path: str, value: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Private Google Sheet transport for Instantly API requests/results")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap")
    load = sub.add_parser("load")
    load.add_argument("--request-id", required=True)
    load.add_argument("--output", required=True)
    result = sub.add_parser("result")
    result.add_argument("--request-id", required=True)
    result.add_argument("--public-result", required=True)
    result.add_argument("--private-result", required=True)
    args = parser.parse_args()
    try:
        if args.command == "bootstrap":
            payload = bootstrap()
        elif args.command == "load":
            payload = load_request(args.request_id)
            _write_json(args.output, payload)
            payload = {"status": "green", "request_id": args.request_id, "loaded": True}
        else:
            with open(args.public_result, encoding="utf-8") as handle:
                public = json.load(handle)
            with open(args.private_result, encoding="utf-8") as handle:
                private = json.load(handle)
            payload = record_result(args.request_id, public, private)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except (PrivateRequestError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"status": "blocked", "detail": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
