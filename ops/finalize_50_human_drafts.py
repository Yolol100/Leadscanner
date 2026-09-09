from __future__ import annotations

import argparse
import hashlib
import imaplib
import json
import os
import re
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from email.policy import SMTP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OPS = ROOT / "ops"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(OPS))

import run_50_personalized_drafts_v6 as human
from outreach_imap_draft import build_draft_message, detect_drafts_folder
from outreach_mailboxes import enabled_mailboxes, load_mailboxes_from_env
from outreach_queue_imap_draft import TERMINAL_FIELDS, inject_private_postal_for_draft, suppression_sets
from outreach_sender import build_sheets_service, get_values, rows_from_values
from prospect_discovery import host_key
from prospect_target_policy import canonical_country

SPREADSHEET_ID = os.getenv("OUTREACH_SPREADSHEET_ID", "").strip()
TARGET = 50
PRETASK_LEAD_COUNT = 175
BASELINE_LEAD_ID = "prospect-25d374063f3f069399d1"
AGENT_TYPE = "quote_intake"
COPY_CONTRACT = "evidence_personalized_v13_5"
FINAL_COPY_CONTRACT = "context_resolved_human_v7"
QUEUE_SHEET = "OutreachQueue"
LEAD_SHEET = "Leadlijst"
SUPPRESSION_SHEET = "Suppression"

DISPLAY_NAME_OVERRIDES = {
    "paarlo.com": "Paarlo Plastics",
    "precisionfittings.com": "Precision Fittings",
    "wrightwoodprecision.com": "Wrightwood Precision",
    "collisongoll.com": "Collison-Goll",
    "chapcoinc.com": "Chapco",
    "threebond.com": "ThreeBond",
    "starkindustrial.com": "Stark Industrial",
    "rablemachineinc.com": "Rable Machine",
    "precisioncncmachining.com": "Lindel Engineering",
    "micro-precision.com": "Micro Precision",
    "spirol.com": "SPIROL",
    "mspmfg.com": "MSP Manufacturing",
    "zeroleak.com": "Zero Leak",
    "eurotronic.nl": "Eurotronic",
}
BAD_NAME_PREFIXES = (
    "blow molded plastic manufacturer",
    "precision turned & machined components",
    "standard and special machined parts",
    "precision machining company",
    "precison cnc machining company",
    "high volume precision machine shop",
    "engineered solutions for fastening",
    "sycamore, il",
    "copper distribution",
    "largest natural stone",
    "creating a safe",
)
BANNED_COPY_RE = re.compile(r"\b(?:ai|automation|bot|roi|agentic|orchestration|agent)\b", re.I)


@dataclass(frozen=True)
class DraftReceipt:
    lead_id: str
    company: str
    email: str
    test_id: str
    folder: str
    readback_count: int
    action: str


def _queue_rows(service):
    headers, rows = rows_from_values(get_values(service, SPREADSHEET_ID, QUEUE_SHEET))
    return headers, [{str(k): str(v or "") for k, v in row.items()} for row in rows]


def _lead_rows(service):
    values = get_values(service, SPREADSHEET_ID, LEAD_SHEET)
    headers = [str(v).strip() for v in values[0]] if values else []
    rows = []
    for idx, raw in enumerate(values[1:], start=2):
        padded = list(raw) + [""] * max(0, len(headers) - len(raw))
        rows.append((idx, {headers[i]: str(padded[i] or "") for i in range(len(headers))}))
    return headers, rows


def _task_new_domains(service) -> set[str]:
    _headers, leads = _lead_rows(service)
    task_rows = leads[PRETASK_LEAD_COUNT:]
    result = set()
    for _row_no, row in task_rows:
        domain = host_key(row.get("Website", ""))
        if domain:
            result.add(domain)
    return result


def _parse_meta(source: str) -> dict:
    if not str(source or "").startswith("agent_offer:"):
        return {}
    try:
        payload = json.loads(str(source).split(":", 1)[1])
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _display_name(row: dict[str, str]) -> str:
    domain = host_key(row.get("website", ""))
    if domain in DISPLAY_NAME_OVERRIDES:
        return DISPLAY_NAME_OVERRIDES[domain]
    raw = re.sub(r"\s+", " ", row.get("company", "")).strip()
    if "|" in raw:
        left = raw.split("|", 1)[0].strip()
        if len(left) >= 3:
            raw = left
    lower = raw.casefold()
    if not raw or lower in {"home", "homepage", "company overview", "portal"}:
        return ""
    if any(lower.startswith(prefix) for prefix in BAD_NAME_PREFIXES):
        return ""
    return raw[:100]


def _word_count_core(body: str) -> int:
    marker = "Not relevant?"
    core = body.split(marker, 1)[0]
    return len(re.findall(r"\b[\w'-]+\b", core))


def _candidate_rows(service) -> list[dict[str, str]]:
    _headers, queue = _queue_rows(service)
    new_domains = _task_new_domains(service)
    suppressed_emails, suppressed_domains = suppression_sets(
        get_values(service, SPREADSHEET_ID, SUPPRESSION_SHEET)
    )
    accepted = []
    seen_domains: set[str] = set()
    seen_emails: set[str] = set()
    seen_anchors: set[str] = set()

    for row in queue:
        if row.get("lead_id", "").strip() == BASELINE_LEAD_ID:
            continue
        if canonical_country(row.get("country", "")) != "US":
            continue
        domain = host_key(row.get("website", ""))
        if not domain or domain not in new_domains or domain in seen_domains:
            continue
        if row.get("status", "").strip().casefold() not in {"prepared", "manual_review", "approved"}:
            continue
        if row.get("verification_status", "").strip().casefold() != "official_site_ready":
            continue
        if any(row.get(field, "").strip() for field in TERMINAL_FIELDS):
            continue
        email = row.get("email", "").strip().casefold()
        email_domain = email.rsplit("@", 1)[1] if "@" in email else ""
        if not email or "@" not in email or email in suppressed_emails or email_domain in suppressed_domains:
            continue
        if email in seen_emails:
            continue

        meta = _parse_meta(row.get("source", ""))
        if str(meta.get("campaign_target_agent_type") or meta.get("agent_type") or "").strip() != AGENT_TYPE:
            continue
        if str(meta.get("copy_contract", "")).strip() != COPY_CONTRACT:
            continue
        if str(meta.get("qualification_tier", "")).strip().upper() != "A":
            continue

        display_name = _display_name(row)
        if not display_name:
            continue
        work = dict(row)
        work["company"] = display_name
        anchor = human._resolve_anchor(work)
        if not anchor or not human._strong(anchor):
            continue
        anchor_key = re.sub(r"\s+", " ", anchor).strip().casefold()
        if anchor_key in seen_anchors:
            continue
        process = human._process(work)
        body = human._english(work, anchor, process)
        subject = f"Quote requests at {display_name}"
        if BANNED_COPY_RE.search(subject) or BANNED_COPY_RE.search(body):
            continue
        core_words = _word_count_core(body)
        if core_words < 40 or core_words > 120:
            continue

        try:
            score = int(str(meta.get("customer_potential", "0") or "0"))
        except ValueError:
            score = 0
        meta["final_human_anchor"] = anchor
        meta["draft_copy_contract"] = FINAL_COPY_CONTRACT
        work["subject"] = subject
        work["body"] = body
        work["status"] = "manual_review"
        work["compliance_status"] = "manual_review"
        work["compliance_basis"] = ""
        work["source"] = "agent_offer:" + json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
        work["__anchor"] = anchor
        work["__score"] = str(score)
        accepted.append(work)
        seen_domains.add(domain)
        seen_emails.add(email)
        seen_anchors.add(anchor_key)

    accepted.sort(key=lambda row: (-int(row.get("__score", "0") or "0"), row.get("lead_id", "")))
    print(f"FINAL_HUMAN_GATE accepted={len(accepted)} target={TARGET}", flush=True)
    return accepted


def _run_prepare_pass(index: int) -> int:
    report = f"prepare-new-only-final-{index}.json"
    cmd = [
        sys.executable,
        str(OPS / "prepare_new_only_v13_5.py"),
        "--target-new",
        "25",
        "--report",
        report,
    ]
    print(f"RUN_NEW_ONLY_PREPARE pass={index}", flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=os.environ.copy(), check=False).returncode


def _batch_update_queue(service, selected: list[dict[str, str]]) -> None:
    headers, queue = _queue_rows(service)
    row_no_by_id = {
        row.get("lead_id", "").strip(): idx
        for idx, row in enumerate(queue, start=2)
        if row.get("lead_id", "").strip()
    }
    data = []
    for row in selected:
        lead_id = row.get("lead_id", "").strip()
        row_no = row_no_by_id.get(lead_id)
        if not row_no:
            raise RuntimeError(f"queue row disappeared for {lead_id}")
        values = [str(row.get(header, "")) for header in headers]
        data.append({"range": f"'{QUEUE_SHEET}'!A{row_no}:AC{row_no}", "values": [values]})
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


def _search_ids(imap, test_id: str) -> tuple[str, ...]:
    status, data = imap.search(None, "HEADER", "X-Webactueel-Draft-Test-ID", f'"{test_id}"')
    if status != "OK":
        raise RuntimeError("IMAP draft search failed")
    if not data or not data[0]:
        return ()
    return tuple(
        part.decode("ascii", errors="replace") if isinstance(part, bytes) else str(part)
        for part in data[0].split()
    )


def _append_or_readback(mailbox, row: dict[str, str], body: str, test_id: str) -> DraftReceipt:
    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    try:
        status, _ = imap.login(mailbox.mail_user, mailbox.mail_password)
        if status != "OK":
            raise RuntimeError("IMAP authentication failed")
        status, listed = imap.list()
        if status != "OK":
            raise RuntimeError("IMAP LIST failed")
        folder = detect_drafts_folder(listed or (), explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""))
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError("failed to select Drafts folder")
        existing = _search_ids(imap, test_id)
        if len(existing) > 1:
            raise RuntimeError(f"duplicate draft test id already exists: {test_id}")
        if len(existing) == 1:
            return DraftReceipt(row["lead_id"], row["company"], row["email"], test_id, folder, 1, "existing")

        msg = build_draft_message(
            sender_name=mailbox.sender_name,
            sender_email=mailbox.sender_email,
            recipient=row["email"],
            subject=row["subject"],
            body=body,
            test_id=test_id,
        )
        status, _ = imap.append(folder, r"(\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes(policy=SMTP))
        if status != "OK":
            raise RuntimeError("IMAP APPEND failed")
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError("failed to reselect Drafts folder")
        created = _search_ids(imap, test_id)
        if len(created) != 1:
            raise RuntimeError(f"draft readback expected one message, found {len(created)}")
        return DraftReceipt(row["lead_id"], row["company"], row["email"], test_id, folder, 1, "appended")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _verify_all(mailbox, test_ids: list[str]) -> tuple[str, int]:
    context = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(mailbox.imap_host, mailbox.imap_port, ssl_context=context)
    try:
        status, _ = imap.login(mailbox.mail_user, mailbox.mail_password)
        if status != "OK":
            raise RuntimeError("IMAP authentication failed during final readback")
        status, listed = imap.list()
        if status != "OK":
            raise RuntimeError("IMAP LIST failed during final readback")
        folder = detect_drafts_folder(listed or (), explicit_folder=os.getenv("OUTREACH_DRAFT_FOLDER", ""))
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError("failed to select Drafts folder during final readback")
        verified = 0
        for test_id in test_ids:
            ids = _search_ids(imap, test_id)
            if len(ids) != 1:
                raise RuntimeError(f"final readback expected exactly one draft for {test_id}; found {len(ids)}")
            verified += 1
        return folder, verified
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _mark_leads_concept(service, selected: list[dict[str, str]]) -> None:
    _headers, leads = _lead_rows(service)
    selected_by_domain = {host_key(row.get("website", "")): row for row in selected}
    data = []
    matched = set()
    for row_no, lead in leads:
        domain = host_key(lead.get("Website", ""))
        selected = selected_by_domain.get(domain)
        if not selected:
            continue
        matched.add(domain)
        data.append({"range": f"'{LEAD_SHEET}'!A{row_no}", "values": [[selected["company"]]]})
        data.append({"range": f"'{LEAD_SHEET}'!D{row_no}", "values": [["concept"]]})
    if len(matched) != TARGET:
        raise RuntimeError(f"Leadlijst concept readback mapping expected {TARGET}, found {len(matched)}")
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


def _write_json(path: str, payload) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args()

    for name in ("OUTREACH_SPREADSHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON"):
        if not os.getenv(name, "").strip():
            raise RuntimeError(f"{name} is required")
    if not args.count_only:
        for name in ("OUTREACH_MAIL_PASSWORD", "OUTREACH_POSTAL_ADDRESS"):
            if not os.getenv(name, "").strip():
                raise RuntimeError(f"{name} is required")

    service = build_sheets_service()
    selected = _candidate_rows(service)
    if args.count_only:
        print(f"FINAL_HUMAN_READY={len(selected)}")
        return 0

    for pass_no in range(1, 4):
        if len(selected) >= TARGET:
            break
        rc = _run_prepare_pass(pass_no)
        if rc != 0:
            print(f"NEW_ONLY_PASS_WARNING={pass_no} rc={rc}", flush=True)
        service = build_sheets_service()
        selected = _candidate_rows(service)

    if len(selected) < TARGET:
        _write_json("selected-50-final.json", [
            {
                "lead_id": row.get("lead_id", ""),
                "company": row.get("company", ""),
                "website": row.get("website", ""),
                "email": row.get("email", ""),
                "subject": row.get("subject", ""),
                "anchor": row.get("__anchor", ""),
            }
            for row in selected
        ])
        print(f"LEADS50_FINAL=blocked human_ready={len(selected)} target={TARGET} smtp_send=not_invoked", flush=True)
        return 2

    selected = selected[:TARGET]
    _batch_update_queue(service, selected)
    _write_json("selected-50-final.json", [
        {
            "lead_id": row["lead_id"],
            "company": row["company"],
            "website": row["website"],
            "email": row["email"],
            "subject": row["subject"],
            "anchor": row["__anchor"],
            "copy_contract": FINAL_COPY_CONTRACT,
        }
        for row in selected
    ])

    daily_limit = int(os.getenv("OUTREACH_DAILY_LIMIT", "20") or "20")
    mailboxes = enabled_mailboxes(load_mailboxes_from_env(mode="validate", default_daily_limit=daily_limit))
    mailbox_id = os.getenv("OUTREACH_DRAFT_MAILBOX_ID", "primary").strip() or "primary"
    mailbox = next((box for box in mailboxes if box.mailbox_id == mailbox_id), None)
    if mailbox is None:
        raise RuntimeError(f"configured draft mailbox not found: {mailbox_id}")

    receipts: list[DraftReceipt] = []
    for index, row in enumerate(selected, start=1):
        body = inject_private_postal_for_draft(row, row["body"])
        digest = hashlib.sha256(row["lead_id"].encode("utf-8")).hexdigest()[:18]
        test_id = f"leads50-final-20260910-{digest}"
        receipt = _append_or_readback(mailbox, row, body, test_id)
        receipts.append(receipt)
        print(
            f"MYHOST_HUMAN_DRAFT=green index={index} lead_id={row['lead_id']} "
            f"action={receipt.action} folder={receipt.folder} smtp_send=not_invoked",
            flush=True,
        )

    folder, verified = _verify_all(mailbox, [receipt.test_id for receipt in receipts])
    if verified != TARGET:
        raise RuntimeError(f"final IMAP readback expected {TARGET}, got {verified}")

    _mark_leads_concept(service, selected)
    _write_json("draft-receipts-final.json", [receipt.__dict__ for receipt in receipts])
    print(
        f"LEADS50_FINAL=green selected={TARGET} drafts={verified} folder={folder} "
        "copy=context_resolved_human_v7 queue=manual_review smtp_send=not_invoked",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
