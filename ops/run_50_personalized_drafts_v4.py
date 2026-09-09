from __future__ import annotations

import re

import run_50_personalized_drafts_v2 as runner

_original_rows_from_values = runner.rows_from_values


def _compat_rows_from_values(values):
    return [], _original_rows_from_values(values)


runner.rows_from_values = _compat_rows_from_values
_original_selected_rows = runner.selected_rows

_GENERIC_ANCHORS = {
    "quote",
    "quotes",
    "quote request",
    "quote requests",
    "request quote",
    "request a quote",
    "get a quote",
    "request pricing",
    "pricing request",
    "contact",
    "contact us",
    "request",
    "get quote",
}
_FILE_RE = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|jpg|jpeg|png)\b", re.I)
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
_URL_RE = re.compile(r"(?:https?://|www\.)", re.I)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


def _normalise(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()
    return re.sub(r"\s+", " ", value)


def _human_anchor_ok(row: dict[str, str]) -> bool:
    meta = runner.parse_agent_source(row.get("source", ""))
    anchor = str(meta.get("personalization_anchor", "")).strip()
    process = str(meta.get("personalization_process_label", "")).strip()
    if not anchor:
        return False
    if _FILE_RE.search(anchor) or _PHONE_RE.search(anchor) or _URL_RE.search(anchor) or _EMAIL_RE.search(anchor):
        return False
    if not re.search(r"[A-Za-zÀ-ÿ]{3,}", anchor):
        return False
    anchor_norm = _normalise(anchor)
    process_norm = _normalise(process)
    if not anchor_norm or anchor_norm in _GENERIC_ANCHORS:
        return False
    if process_norm and anchor_norm == process_norm:
        return False
    fact = str(meta.get("fact", "")).strip()
    value = str(meta.get("value_asset_summary", "")).strip()
    if not fact or not value:
        return False
    return True


def _human_selected_rows() -> list[dict[str, str]]:
    rows = _original_selected_rows()
    accepted = [row for row in rows if _human_anchor_ok(row)]
    rejected = len(rows) - len(accepted)
    print(f"HUMAN_COPY_GATE accepted={len(accepted)} weak_rejected={rejected}", flush=True)
    return accepted


runner.selected_rows = _human_selected_rows

if __name__ == "__main__":
    raise SystemExit(runner.main())
