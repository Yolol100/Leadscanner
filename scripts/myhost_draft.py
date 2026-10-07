from __future__ import annotations

import argparse
import imaplib
import json
import os
import re
import ssl
import time
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from email.utils import formatdate, make_msgid
from pathlib import Path


MAX_DRAFTS_PER_RUN = 100
LEAD_ID_RE = re.compile(r"^growth-[0-9a-f]{20}$")


def normalize_text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def imap_capability_tokens(client) -> set[str]:
    # imaplib caches capabilities before/around authentication. Some servers
    # advertise additional post-login capabilities, so always refresh when
    # CAPABILITY is available and merge it with the cached greeting values.
    raw = list(getattr(client, "capabilities", ()) or ())
    if hasattr(client, "capability"):
        status, data = client.capability()
        if status == "OK":
            raw.extend(b" ".join(data or []).split())
    tokens = set()
    for value in raw:
        if isinstance(value, bytes):
            value = value.decode("ascii", errors="ignore")
        tokens.add(str(value).upper())
    return tokens


def require_uidplus(client, operation: str) -> None:
    if "UIDPLUS" not in imap_capability_tokens(client):
        raise RuntimeError(
            f"IMAP UIDPLUS is required before {operation}; "
            "target-only deletion cannot be proven"
        )


def uid_for_message_id(client, message_id: bytes) -> bytes:
    status, data = client.fetch(message_id, "(UID)")
    if status != "OK":
        raise RuntimeError("Could not resolve IMAP UID for target draft")
    for item in data or []:
        meta = item[0] if isinstance(item, tuple) and item else item
        if isinstance(meta, str):
            meta = meta.encode()
        if isinstance(meta, (bytes, bytearray)):
            match = re.search(rb"\bUID\s+(\d+)\b", bytes(meta))
            if match:
                return match.group(1)
    raise RuntimeError("IMAP UID readback omitted target UID")


def fetch_message_uid(client, uid: bytes) -> EmailMessage:
    status, data = client.uid("fetch", uid.decode("ascii"), "(RFC822)")
    if status != "OK":
        raise RuntimeError(
            f"Could not fetch draft UID {uid.decode('ascii', errors='replace')}"
        )
    for item in data or []:
        if (
            isinstance(item, tuple)
            and len(item) >= 2
            and isinstance(item[1], (bytes, bytearray))
        ):
            return BytesParser(policy=default).parsebytes(bytes(item[1]))
    raise RuntimeError("IMAP UID readback returned no message bytes")


def uid_expunge_only(
    client,
    folder: str,
    uid: bytes,
    *,
    operation: str,
    ensure_selected: bool = True,
    capability_tokens: set[str] | None = None,
) -> None:
    if capability_tokens is None:
        require_uidplus(client, operation)
    elif "UIDPLUS" not in capability_tokens:
        raise RuntimeError(
            f"IMAP UIDPLUS is required before {operation}; "
            "target-only deletion cannot be proven"
        )
    if ensure_selected:
        select_folder(client, folder, readonly=False)
    uid_text = uid.decode("ascii")
    status, _ = client.uid("store", uid_text, "+FLAGS", "(\\Deleted)")
    if status != "OK":
        raise RuntimeError(f"Could not mark target draft UID deleted during {operation}")
    status, _ = client.uid("expunge", uid_text)
    if status != "OK":
        # Best-effort rollback of the target flag; never fall back to broad EXPUNGE.
        try:
            client.uid("store", uid_text, "-FLAGS", "(\\Deleted)")
        except Exception:
            pass
        raise RuntimeError(f"Could not UID-expunge target draft during {operation}")


def stable_lead_id(row: dict) -> str:
    existing = normalize_text(row.get("lead_id"))
    if not LEAD_ID_RE.fullmatch(existing):
        raise RuntimeError("mijn.host requires a canonical reviewed growth-<20 hex> lead_id")
    return existing


def build_message(row: dict) -> tuple[str, EmailMessage]:
    status = str(row.get("status") or "")
    basis = str(row.get("contact_basis_status") or "")
    if status not in {"draft_ready", "review_draft"}:
        raise RuntimeError("Only draft_ready or review_draft rows may enter mijn.host")
    if status == "draft_ready" and basis != "pass":
        raise RuntimeError("draft_ready requires contact_basis_status=pass")
    if status == "review_draft" and basis != "review_required":
        raise RuntimeError("review_draft requires contact_basis_status=review_required")

    email = normalize_text(row.get("email"))
    subject = normalize_text(row.get("subject"))
    body = normalize_text(row.get("body"))
    if not email or not subject or not body:
        raise RuntimeError("draft_ready row is missing email, subject or body")

    lead_id = stable_lead_id(row)
    sender_name = os.getenv("OUTREACH_SENDER_NAME", "Andrew Baeten").strip()
    sender_email = os.getenv("OUTREACH_SENDER_EMAIL", "info@andrewbaeten.nl").strip()

    msg = EmailMessage(policy=default)
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender_email.split("@")[-1] if "@" in sender_email else None)
    msg["X-Webactueel-Lead-ID"] = lead_id
    if status == "review_draft":
        msg["X-Webactueel-Review-Required"] = "contact-basis"
    msg.set_content(body)
    return lead_id, msg


def connect_imap():
    host = os.getenv("OUTREACH_IMAP_HOST", "mail.andrewbaeten.nl").strip()
    port = int(os.getenv("OUTREACH_IMAP_PORT", "993"))
    user = os.getenv("OUTREACH_MAIL_USER", "info@andrewbaeten.nl").strip()
    password = os.getenv("OUTREACH_MAIL_PASSWORD", "")
    timeout = float(os.getenv("OUTREACH_IMAP_TIMEOUT_SECONDS", "15"))
    retries = int(os.getenv("OUTREACH_IMAP_CONNECT_RETRIES", "3"))
    retry_delay = float(os.getenv("OUTREACH_IMAP_RETRY_DELAY_SECONDS", "2"))
    if not password:
        raise RuntimeError("OUTREACH_MAIL_PASSWORD is required when drafts are ready")
    if timeout <= 0 or retries < 1 or retry_delay < 0:
        raise RuntimeError("Invalid IMAP retry/timeout configuration")

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        client = None
        try:
            client = imaplib.IMAP4_SSL(
                host,
                port,
                ssl_context=ssl.create_default_context(),
                timeout=timeout,
            )
            client.login(user, password)
            return client
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
            last_error = exc
            if client is not None:
                try:
                    client.shutdown()
                except Exception:
                    pass
            if attempt < retries:
                time.sleep(retry_delay)

    raise RuntimeError(
        f"IMAP connection/login failed after {retries} attempt(s): {last_error}"
    )


def find_drafts_folder(client) -> str:
    preferred = os.getenv("OUTREACH_DRAFT_FOLDER", "").strip()
    if preferred:
        return preferred

    status, rows = client.list()
    if status != "OK":
        raise RuntimeError("Could not list IMAP folders")

    choices: list[str] = []
    for raw in rows or []:
        text = raw.decode("utf-8", errors="replace")
        match = re.search(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*$', text)
        folder = match.group(1).replace('\\\"', '"') if match else text.split()[-1].strip('"')
        choices.append(folder)

    for folder in choices:
        low = folder.casefold()
        if "draft" in low or "concept" in low:
            return folder
    raise RuntimeError("No Drafts/Concepten IMAP folder found")


def select_folder(client, folder: str, *, readonly: bool = True) -> None:
    if client.select(f'"{folder}"', readonly=readonly)[0] != "OK":
        raise RuntimeError("Could not open drafts folder")


def find_message_ids(client, folder: str, lead_id: str, *, ensure_selected: bool = True) -> list[bytes]:
    if ensure_selected:
        select_folder(client, folder)
    status, data = client.search(None, "HEADER", "X-Webactueel-Lead-ID", f'"{lead_id}"')
    if status != "OK":
        raise RuntimeError(f"Could not search draft readback for {lead_id}")
    return list((data[0] if data else b"").split())


def fetch_message(client, message_id: bytes) -> EmailMessage:
    status, data = client.fetch(message_id, "(RFC822)")
    if status != "OK":
        raise RuntimeError("Could not fetch draft for readback")
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return BytesParser(policy=default).parsebytes(bytes(item[1]))
    raise RuntimeError("IMAP readback returned no message bytes")


def plain_body(msg: EmailMessage) -> str:
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain",))
        return normalize_text(part.get_content() if part else "")
    return normalize_text(msg.get_content())


def exact_message_matches(actual: EmailMessage, expected: EmailMessage) -> bool:
    return (
        normalize_text(actual.get("To", "")) == normalize_text(expected.get("To", ""))
        and normalize_text(actual.get("Subject", "")) == normalize_text(expected.get("Subject", ""))
        and normalize_text(actual.get("X-Webactueel-Lead-ID", ""))
        == normalize_text(expected.get("X-Webactueel-Lead-ID", ""))
        and normalize_text(actual.get("X-Webactueel-Review-Required", ""))
        == normalize_text(expected.get("X-Webactueel-Review-Required", ""))
        and plain_body(actual) == plain_body(expected)
    )


def require_existing_drafts(
    client,
    folder: str,
    prepared: list[tuple[dict, str, EmailMessage]],
) -> None:
    select_folder(client, folder, readonly=True)
    for row, lead_id, expected in prepared:
        existing = find_message_ids(client, folder, lead_id, ensure_selected=False)
        if len(existing) != 1:
            raise RuntimeError(
                f"rewrite-existing-only requires exactly one existing draft for {lead_id}, found {len(existing)}"
            )
        actual = fetch_message(client, existing[0])
        if normalize_text(actual.get("X-Webactueel-Lead-ID", "")) != lead_id:
            raise RuntimeError(f"Existing draft identity mismatch for {lead_id}")
        if normalize_text(actual.get("To", "")) != normalize_text(expected.get("To", "")):
            raise RuntimeError(f"Existing draft recipient mismatch for {lead_id}")
        if normalize_text(actual.get("X-Webactueel-Review-Required", "")) != normalize_text(
            expected.get("X-Webactueel-Review-Required", "")
        ):
            raise RuntimeError(f"Existing draft review status mismatch for {lead_id}")


def _rollback_appended_uid(client, folder: str, uid: bytes, lead_id: str, cause: Exception) -> None:
    try:
        uid_expunge_only(
            client,
            folder,
            uid,
            operation=f"rollback appended draft for {lead_id}",
        )
    except Exception as rollback_exc:
        raise RuntimeError(
            f"{cause}; rollback of newly appended draft failed: {rollback_exc}"
        ) from cause


def append_and_verify(client, folder: str, lead_id: str, msg: EmailMessage, *, reject_changed_existing: bool = False) -> str:
    existing = find_message_ids(client, folder, lead_id)
    if len(existing) > 1:
        raise RuntimeError(f"Expected at most one existing draft for {lead_id}, found {len(existing)}")

    # Every APPEND must have a target-only rollback path before the write starts.
    require_uidplus(client, f"draft append for {lead_id}")

    existing_uid = None
    existing_snapshot = None
    if existing:
        actual = fetch_message(client, existing[0])
        if exact_message_matches(actual, msg):
            return "existing"
        if reject_changed_existing:
            raise RuntimeError(
                f"Changed existing draft for {lead_id}; automatic replacement is disabled"
            )
        existing_uid = uid_for_message_id(client, existing[0])
        existing_snapshot = actual

    raw = msg.as_bytes(policy=default)
    status, _ = client.append(
        folder,
        "(\\Draft)",
        imaplib.Time2Internaldate(__import__("time").time()),
        raw,
    )
    if status != "OK":
        raise RuntimeError(f"IMAP APPEND failed for {lead_id}")

    new_uid = None
    old_removed = False
    try:
        ids_after_append = find_message_ids(client, folder, lead_id)
        new_ids = [message_id for message_id in ids_after_append if message_id not in existing]
        if len(new_ids) != 1:
            raise RuntimeError(
                f"Expected one new draft after append for {lead_id}, found {len(new_ids)}"
            )
        new_uid = uid_for_message_id(client, new_ids[0])
        new_actual = fetch_message_uid(client, new_uid)
        if not exact_message_matches(new_actual, msg):
            raise RuntimeError(f"Draft UID readback mismatch for {lead_id}")

        if existing:
            current_old = fetch_message_uid(client, existing_uid)
            if normalize_text(current_old.get("X-Webactueel-Lead-ID", "")) != lead_id:
                raise RuntimeError(f"Existing draft identity changed before replacement for {lead_id}")
            if not exact_message_matches(current_old, existing_snapshot):
                raise RuntimeError(f"Existing draft changed before target-only replacement for {lead_id}")
            uid_expunge_only(
                client,
                folder,
                existing_uid,
                operation=f"bounded draft replacement for {lead_id}",
            )
            old_removed = True

            final_ids = find_message_ids(client, folder, lead_id)
            if len(final_ids) != 1:
                raise RuntimeError(
                    f"Expected one final draft after replacement for {lead_id}, found {len(final_ids)}"
                )
            final_actual = fetch_message(client, final_ids[0])
            if not exact_message_matches(final_actual, msg):
                raise RuntimeError(f"Final replacement readback mismatch for {lead_id}")
            return "replaced"

        if len(ids_after_append) != 1:
            raise RuntimeError(f"Expected one draft after append for {lead_id}, found {len(ids_after_append)}")
        return "created"
    except Exception as exc:
        if new_uid is not None and not old_removed:
            _rollback_appended_uid(client, folder, new_uid, lead_id, exc)
        raise


def create_drafts(batch: dict, *, rewrite_existing_only: bool = False, reject_changed_existing: bool = False) -> dict:
    rows = [
        row
        for row in (batch.get("rows") or [])
        if row.get("status") in {"draft_ready", "review_draft"}
    ]
    if len(rows) > MAX_DRAFTS_PER_RUN:
        raise RuntimeError(f"At most {MAX_DRAFTS_PER_RUN} drafts may be created per run")

    prepared: list[tuple[dict, str, EmailMessage]] = []
    for row in rows:
        lead_id, msg = build_message(row)
        prepared.append((row, lead_id, msg))

    if not prepared:
        return {
            "eligible_count": 0,
            "created_count": 0,
            "existing_count": 0,
            "replaced_count": 0,
            "draft_folder": None,
            "review_required_count": 0,
            "items": [],
            "smtp_send": "not_available",
            "rewrite_existing_only": rewrite_existing_only,
            "reject_changed_existing": reject_changed_existing,
        }

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        if rewrite_existing_only:
            require_existing_drafts(client, folder, prepared)
        created = 0
        existing = 0
        replaced = 0
        items = []
        for row, lead_id, msg in prepared:
            outcome = append_and_verify(client, folder, lead_id, msg, reject_changed_existing=reject_changed_existing)
            if outcome == "created":
                created += 1
            elif outcome == "replaced":
                replaced += 1
            else:
                existing += 1

            final_ids = find_message_ids(client, folder, lead_id)
            if len(final_ids) != 1:
                raise RuntimeError(
                    f"Expected exactly one final draft for readback {lead_id}, found {len(final_ids)}"
                )
            actual = fetch_message(client, final_ids[0])
            if not exact_message_matches(actual, msg):
                raise RuntimeError(f"Final exact readback mismatch for {lead_id}")
            items.append(
                {
                    "lead_id": lead_id,
                    "to": normalize_text(actual.get("To", "")),
                    "subject": normalize_text(actual.get("Subject", "")),
                    "body": plain_body(actual),
                    "review_status": normalize_text(
                        actual.get("X-Webactueel-Review-Required", "")
                    ) or "not-required",
                    "outcome": outcome,
                }
            )
        return {
            "eligible_count": len(rows),
            "created_count": created,
            "existing_count": existing,
            "replaced_count": replaced,
            "draft_folder": folder,
            "review_required_count": sum(1 for row in rows if row.get("status") == "review_draft"),
            "items": items,
            "smtp_send": "not_available",
            "rewrite_existing_only": rewrite_existing_only,
            "reject_changed_existing": reject_changed_existing,
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--rewrite-existing-only",
        action="store_true",
        help="Require one matching draft for every lead before writing; never create missing drafts.",
    )
    parser.add_argument(
        "--reject-changed-existing",
        action="store_true",
        help="Allow exact retries but reject any changed existing draft instead of replacing it.",
    )
    args = parser.parse_args()

    batch = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    result = create_drafts(
        batch,
        rewrite_existing_only=args.rewrite_existing_only,
        reject_changed_existing=args.reject_changed_existing,
    )
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "MYHOST_DRAFT_SYNC=green "
        f"eligible={result['eligible_count']} "
        f"created={result['created_count']} "
        f"existing={result['existing_count']} "
        f"replaced={result['replaced_count']} "
        f"review_required={result['review_required_count']} "
        f"rewrite_existing_only={str(result['rewrite_existing_only']).lower()} "
        f"reject_changed_existing={str(result['reject_changed_existing']).lower()} "
        "smtp_send=not_available"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
