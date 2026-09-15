from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

API_ORIGIN = "https://api.instantly.ai"
API_PREFIX = "/api/v2"
OPENAPI_URL = "https://api.instantly.ai/openapi/api_v2.json"
HTTP_METHODS = {"GET", "POST", "PATCH", "DELETE", "PUT"}
SENSITIVE_KEY_RE = re.compile(
    r"(?:email|phone|body|subject|content|first_name|last_name|name|signature|password|token|api[_-]?key|secret|authorization|custom_variables)",
    re.IGNORECASE,
)


class InstantlyApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class OperationMatch:
    method: str
    concrete_path: str
    template_path: str
    operation_id: str
    tags: tuple[str, ...]
    risk: str


@dataclass(frozen=True)
class ExecuteResult:
    status: str
    applied: bool
    risk: str
    method: str
    path: str
    template_path: str
    operation_id: str
    confirmation_token: str
    response_status: int | None = None
    response_shape: str = ""
    response_count: int | None = None
    verification_status: str = "not_requested"

    def public_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "applied": self.applied,
            "risk": self.risk,
            "method": self.method,
            "path": self.template_path,
            "operation_id": self.operation_id,
            "confirmation_token": self.confirmation_token,
            "response_status": self.response_status,
            "response_shape": self.response_shape,
            "verification_status": self.verification_status,
        }
        if self.response_count is not None:
            result["response_count"] = self.response_count
        return result


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def confirmation_token(method: str, path: str, query: Any, body: Any) -> str:
    material = "\n".join([
        method.upper(),
        path,
        _canonical_json(query if query is not None else {}),
        _canonical_json(body if body is not None else {}),
    ])
    return "CONFIRM-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def normalize_path(path: str) -> str:
    value = (path or "").strip()
    if not value.startswith("/"):
        raise ValueError("path must be relative and start with /")
    if "://" in value or value.startswith("//"):
        raise ValueError("absolute/network paths are not allowed")
    parsed = urllib.parse.urlsplit(value)
    if parsed.query or parsed.fragment:
        raise ValueError("put query parameters in query_json, not in path")
    normalized = re.sub(r"/{2,}", "/", parsed.path)
    if normalized == API_PREFIX:
        return normalized
    if normalized.startswith(API_PREFIX + "/"):
        return normalized
    return API_PREFIX + normalized


def _template_regex(template: str) -> re.Pattern[str]:
    pieces: list[str] = []
    for part in template.strip("/").split("/"):
        if part.startswith("{") and part.endswith("}"):
            pieces.append(r"[^/]+")
        else:
            pieces.append(re.escape(part))
    return re.compile(r"^/" + "/".join(pieces) + r"/?$")


def load_openapi(*, url: str = OPENAPI_URL, timeout: float = 30.0) -> dict[str, Any]:
    local_path = os.getenv("INSTANTLY_OPENAPI_FILE", "").strip()
    if local_path:
        with open(local_path, encoding="utf-8") as handle:
            return json.load(handle)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "webactueel-leadscanner/instantly-api-v2"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(25_000_001)
    except urllib.error.HTTPError as exc:
        raise InstantlyApiError(f"OpenAPI fetch failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise InstantlyApiError("OpenAPI fetch failed") from exc
    if len(raw) > 25_000_000:
        raise InstantlyApiError("OpenAPI response exceeded safety limit")
    try:
        spec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstantlyApiError("OpenAPI response was invalid JSON") from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise InstantlyApiError("OpenAPI document is missing paths")
    return spec


def classify_risk(method: str, template_path: str, operation_id: str = "") -> str:
    method = method.upper()
    text = f"{template_path} {operation_id}".lower()
    if method == "GET":
        return "read"
    if method == "DELETE":
        return "destructive"
    high_effect_markers = (
        "/emails/reply",
        "/emails/forward",
        "/emails/test",
        "/campaigns/{id}/activate",
        "/campaigns/{id}/resume",
        "/subsequences/{id}/resume",
        "workspace removal",
        "schedule-current-workspace-removal",
        "change-workspace-owner",
        "dfy",
        "api-key",
        "api key",
        "order",
        "enrichment",
        "inbox-placement-tests",
    )
    if any(marker in text for marker in high_effect_markers):
        return "high_impact"
    return "write"


def match_operation(spec: Mapping[str, Any], method: str, path: str) -> OperationMatch:
    method = method.upper().strip()
    if method not in HTTP_METHODS:
        raise ValueError("unsupported HTTP method")
    concrete = normalize_path(path)
    candidates: list[tuple[int, str, Mapping[str, Any]]] = []
    for template, item in (spec.get("paths") or {}).items():
        if not str(template).startswith(API_PREFIX):
            continue
        operation = (item or {}).get(method.lower()) if isinstance(item, Mapping) else None
        if not isinstance(operation, Mapping):
            continue
        if _template_regex(str(template)).fullmatch(concrete):
            literal_score = len(re.sub(r"\{[^}]+\}", "", str(template)))
            candidates.append((literal_score, str(template), operation))
    if not candidates:
        raise InstantlyApiError("requested operation is not present in the official Instantly API v2 OpenAPI document")
    _, template, operation = max(candidates, key=lambda row: row[0])
    operation_id = str(operation.get("operationId") or "")
    tags = tuple(str(tag) for tag in (operation.get("tags") or []))
    return OperationMatch(
        method=method,
        concrete_path=concrete,
        template_path=template,
        operation_id=operation_id,
        tags=tags,
        risk=classify_risk(method, template, operation_id),
    )


def catalog(spec: Mapping[str, Any]) -> dict[str, Any]:
    by_method: dict[str, int] = {}
    by_tag: dict[str, int] = {}
    operations = 0
    for template, item in (spec.get("paths") or {}).items():
        if not str(template).startswith(API_PREFIX) or not isinstance(item, Mapping):
            continue
        for method, operation in item.items():
            if method.upper() not in HTTP_METHODS or not isinstance(operation, Mapping):
                continue
            operations += 1
            by_method[method.upper()] = by_method.get(method.upper(), 0) + 1
            tags = operation.get("tags") or ["untagged"]
            for tag in tags:
                key = str(tag)
                by_tag[key] = by_tag.get(key, 0) + 1
    return {
        "status": "green",
        "api": "Instantly API v2",
        "operations": operations,
        "methods": dict(sorted(by_method.items())),
        "categories": dict(sorted(by_tag.items())),
        "source": OPENAPI_URL,
    }


def _shape(value: Any) -> tuple[str, int | None]:
    if value is None:
        return "empty", 0
    if isinstance(value, list):
        return "list", len(value)
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            return "object_items", len(value["items"])
        return "object", len(value)
    return type(value).__name__, None


def sanitize_public(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = sanitize_public(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize_public(item) for item in value[:20]]
    if isinstance(value, str):
        if "@" in value or len(value) > 160:
            return "[redacted]"
        return value
    return value


class InstantlyApiV2Client:
    def __init__(self, api_key: str, *, timeout: float = 45.0):
        key = (api_key or "").strip()
        if not key:
            raise InstantlyApiError("INSTANTLY_API_KEY is required")
        self._api_key = key
        self.timeout = timeout

    def request(self, method: str, path: str, *, query: Mapping[str, Any] | None = None, body: Any = None) -> tuple[int, Any]:
        concrete = normalize_path(path)
        url = API_ORIGIN + concrete
        if query:
            encoded = urllib.parse.urlencode(
                [(str(k), str(v).lower() if isinstance(v, bool) else str(v)) for k, v in query.items() if v is not None],
                doseq=True,
            )
            if encoded:
                url += "?" + encoded
        payload = None if body is None else _canonical_json(body).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "webactueel-leadscanner/instantly-api-v2",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=payload, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = int(getattr(response, "status", 200))
                raw = response.read(10_000_001)
        except urllib.error.HTTPError as exc:
            raise InstantlyApiError(f"Instantly API HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise InstantlyApiError("Instantly API connection failed") from exc
        if len(raw) > 10_000_000:
            raise InstantlyApiError("Instantly API response exceeded safety limit")
        if not raw:
            return status, None
        content_type = response.headers.get("Content-Type", "") if hasattr(response, "headers") else ""
        if "json" not in content_type.lower():
            return status, {"non_json_response_bytes": len(raw)}
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InstantlyApiError("Instantly API returned invalid JSON") from exc


def execute_operation(
    *,
    client: InstantlyApiV2Client,
    spec: Mapping[str, Any],
    method: str,
    path: str,
    query: Mapping[str, Any] | None = None,
    body: Any = None,
    apply: bool = False,
    confirmation: str = "",
    verify: Mapping[str, Any] | None = None,
) -> tuple[ExecuteResult, Any, Any]:
    op = match_operation(spec, method, path)
    token = confirmation_token(op.method, op.concrete_path, query or {}, body if body is not None else {})
    if op.risk != "read" and not apply:
        result = ExecuteResult(
            status="planned",
            applied=False,
            risk=op.risk,
            method=op.method,
            path=op.concrete_path,
            template_path=op.template_path,
            operation_id=op.operation_id,
            confirmation_token=token,
            verification_status="not_run",
        )
        return result, None, None
    if op.risk in {"destructive", "high_impact"} and confirmation.strip() != token:
        raise InstantlyApiError("exact confirmation token is required for destructive/high-impact operations")
    status, payload = client.request(op.method, op.concrete_path, query=query, body=body)
    shape, count = _shape(payload)
    verification_payload = None
    verification_status = "not_requested"
    if verify:
        verify_method = str(verify.get("method") or "GET").upper()
        verify_path = str(verify.get("path") or "")
        verify_query = verify.get("query") if isinstance(verify.get("query"), Mapping) else None
        verify_body = verify.get("body")
        match_operation(spec, verify_method, verify_path)
        _, verification_payload = client.request(verify_method, verify_path, query=verify_query, body=verify_body)
        verification_status = "readback_ok"
    result = ExecuteResult(
        status="green",
        applied=op.risk != "read",
        risk=op.risk,
        method=op.method,
        path=op.concrete_path,
        template_path=op.template_path,
        operation_id=op.operation_id,
        confirmation_token=token,
        response_status=status,
        response_shape=shape,
        response_count=count,
        verification_status=verification_status,
    )
    return result, payload, verification_payload


def _load_json_file(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Full-surface Instantly API v2 executor with OpenAPI validation")
    sub = parser.add_subparsers(dest="command", required=True)
    catalog_parser = sub.add_parser("catalog")
    catalog_parser.add_argument("--report", default="")
    request_parser = sub.add_parser("request")
    request_parser.add_argument("--request-json", required=True)
    request_parser.add_argument("--report", default="")
    args = parser.parse_args()
    try:
        spec = load_openapi()
        if args.command == "catalog":
            public = catalog(spec)
        else:
            request_data = _load_json_file(args.request_json)
            if not isinstance(request_data, dict):
                raise ValueError("request JSON must be an object")
            client = InstantlyApiV2Client(os.getenv("INSTANTLY_API_KEY", ""))
            result, _, _ = execute_operation(
                client=client,
                spec=spec,
                method=str(request_data.get("method") or ""),
                path=str(request_data.get("path") or ""),
                query=request_data.get("query") if isinstance(request_data.get("query"), Mapping) else None,
                body=request_data.get("body"),
                apply=bool(request_data.get("apply", False)),
                confirmation=str(request_data.get("confirmation") or ""),
                verify=request_data.get("verify") if isinstance(request_data.get("verify"), Mapping) else None,
            )
            public = result.public_dict()
        if args.report:
            with open(args.report, "w", encoding="utf-8") as handle:
                json.dump(public, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(public, ensure_ascii=False, sort_keys=True))
        return 0
    except (InstantlyApiError, ValueError, OSError, json.JSONDecodeError) as exc:
        blocked = {"status": "blocked", "detail": str(exc)}
        if getattr(args, "report", ""):
            with open(args.report, "w", encoding="utf-8") as handle:
                json.dump(blocked, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(blocked, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
