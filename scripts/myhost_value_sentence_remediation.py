from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import time
from collections import Counter
from copy import deepcopy
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default
from email.utils import formatdate, make_msgid
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from myhost_draft import (
    LEAD_ID_RE,
    connect_imap,
    fetch_message_uid,
    find_drafts_folder,
    normalize_text,
    plain_body,
    select_folder,
    imap_capability_tokens,
    require_uidplus,
)
from myhost_fast_mailbox import (
    bulk_fetch_uid_messages,
    bulk_inventory_drafts,
    current_from_inventory,
    replace_known_draft_and_verify,
    snapshot_message,
    uid_from_inventory,
)
from prepare_growth_batch import build_value_sentence

STATE_VERSION = "leadscanner-value-sentence-state-v1"
STATE_TTL_SECONDS = 4 * 60 * 60
MAX_REMEDIATION = 450
HEADER_FETCH = "(BODY.PEEK[HEADER.FIELDS (X-Webactueel-Lead-ID)])"
HEADER_CHUNK = 250

NL_GENERAL = "Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:"
EN_GENERAL = "My Growth Subscription covers several parts of your online presence:"
NL_TAILORED = re.compile(
    r"^Voor .+ brengt mijn Groeiabonnement website, vindbaarheid, content, "
    r"automatisering en hosting samen met één vast aanspreekpunt:$"
)
EN_TAILORED = re.compile(
    r"^For .+, my Growth Subscription brings website, search visibility, content, "
    r"automation and hosting together with one fixed point of contact:$"
)
BODY_LAYOUT = re.compile(
    r"\A(?P<greeting>Hallo,|Goedendag,|Hello,)\n\n"
    r"(?P<opening>[^\n]+)\n\n"
    r"(?P<value>[^\n]+)\n\n"
    r"(?P<rest>.+)\Z",
    re.DOTALL,
)


def _state_key(secret: str, repository: str) -> bytes:
    if not secret:
        raise RuntimeError("state encryption secret is required")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"leadscanner-value-sentence-state-v1",
        info=str(repository or "Yolol100/Leadscanner").encode("utf-8"),
    ).derive(secret.encode("utf-8"))


def encrypt_state(payload: dict, secret: str, repository: str) -> dict:
    nonce = os.urandom(12)
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(_state_key(secret, repository)).encrypt(
        nonce, raw, STATE_VERSION.encode("ascii")
    )
    return {
        "version": STATE_VERSION,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_state(envelope: dict, secret: str, repository: str) -> dict:
    if envelope.get("version") != STATE_VERSION:
        raise ValueError("unsupported audit state version")
    try:
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    except Exception as exc:
        raise ValueError("invalid encrypted audit state") from exc
    raw = AESGCM(_state_key(secret, repository)).decrypt(
        nonce, ciphertext, STATE_VERSION.encode("ascii")
    )
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("audit state must decode to an object")
    return payload


def _uid_from_meta(meta: bytes) -> bytes | None:
    match = re.search(rb"\bUID\s+(\d+)\b", meta or b"")
    return match.group(1) if match else None


def growth_uid_index(client, folder: str) -> list[tuple[str, bytes]]:
    select_folder(client, folder, readonly=True)
    status, data = client.uid("search", None, "ALL")
    if status != "OK":
        raise RuntimeError("Could not inventory current drafts by UID")
    all_uids = sorted(
        list((data[0] if data else b"").split()),
        key=lambda value: int(value),
    )
    pairs: list[tuple[str, bytes]] = []
    for start in range(0, len(all_uids), HEADER_CHUNK):
        chunk = all_uids[start:start + HEADER_CHUNK]
        if not chunk:
            continue
        status, rows = client.uid(
            "fetch",
            b",".join(chunk).decode("ascii"),
            HEADER_FETCH,
        )
        if status != "OK":
            raise RuntimeError("Could not fetch draft identity headers")
        for item in rows or []:
            if not (
                isinstance(item, tuple)
                and len(item) >= 2
                and isinstance(item[1], (bytes, bytearray))
            ):
                continue
            meta = (
                bytes(item[0])
                if isinstance(item[0], (bytes, bytearray))
                else str(item[0]).encode()
            )
            uid = _uid_from_meta(meta)
            if uid is None:
                raise RuntimeError("UID header inventory omitted UID metadata")
            header = BytesParser(policy=default).parsebytes(bytes(item[1]))
            lead_id = normalize_text(header.get("X-Webactueel-Lead-ID", ""))
            if LEAD_ID_RE.fullmatch(lead_id):
                pairs.append((lead_id, uid))

    pairs.sort(key=lambda item: int(item[1]))
    counts = Counter(lead_id for lead_id, _ in pairs)
    duplicate = next((lead_id for lead_id, count in counts.items() if count != 1), None)
    if duplicate:
        raise RuntimeError("Duplicate Growth draft identity detected; remediation blocked")
    return pairs


def _valid_value_line(value: str, language: str) -> bool:
    if language == "en":
        return value == EN_GENERAL or bool(EN_TAILORED.fullmatch(value))
    return value == NL_GENERAL or bool(NL_TAILORED.fullmatch(value))


def analyze_body(body: str) -> dict:
    text = normalize_text(body)
    match = BODY_LAYOUT.fullmatch(text)
    if not match:
        raise ValueError("unsupported_growth_layout")

    greeting = match.group("greeting")
    opening = match.group("opening").strip()
    value = match.group("value").strip()
    rest = match.group("rest")
    language = "en" if greeting == "Hello," else "nl"

    if not 3 <= len(value) <= 500:
        raise ValueError("invalid_value_sentence_slot")

    lines = rest.splitlines()
    bullets = [line for line in lines if line.startswith("• ")]
    if len(bullets) != 6 or not lines or not lines[0].startswith("• "):
        raise ValueError("canonical_six_bullets_missing")
    if "€250–€500" not in rest:
        raise ValueError("canonical_price_missing")
    if language == "en":
        if "Would you like me to make a no-obligation example design for " not in rest:
            raise ValueError("canonical_cta_missing")
    elif "Zal ik vrijblijvend een voorbeeld design maken voor " not in rest:
        raise ValueError("canonical_cta_missing")

    expected_value = build_value_sentence(opening, language)
    start, end = match.span("value")
    expected_body = text[:start] + expected_value + text[end:]
    return {
        "language": language,
        "opening": opening,
        "current_value": value,
        "expected_value": expected_value,
        "expected_body": expected_body,
        "tailored": expected_value not in {NL_GENERAL, EN_GENERAL},
    }


def _header_text(value: object) -> str:
    return (
        re.sub(r"\\r?\\n[ \\t]*", " ", str(value or ""))
        .replace("\\r", " ")
        .replace("\\n", " ")
        .strip()
    )


def _x_headers(msg: EmailMessage) -> list[list[str]]:
    rows = []
    for key, value in msg.items():
        if key.casefold().startswith("x-webactueel-"):
            rows.append([key.casefold(), _header_text(value)])
    rows.sort()
    return rows


def full_snapshot(msg: EmailMessage) -> dict:
    return {
        "from": _header_text(msg.get("From", "")),
        "to": _header_text(msg.get("To", "")),
        "subject": _header_text(msg.get("Subject", "")),
        "lead_id": _header_text(msg.get("X-Webactueel-Lead-ID", "")),
        "review_status": _header_text(msg.get("X-Webactueel-Review-Required", "")),
        "body": plain_body(msg),
        "x_headers": _x_headers(msg),
    }


def snapshot_with_body(snapshot: dict, body: str) -> dict:
    result = deepcopy(snapshot)
    result["body"] = normalize_text(body)
    return result


def message_with_body(current: EmailMessage, body: str) -> EmailMessage:
    expected = EmailMessage(policy=default)
    skip = {
        "content-type",
        "content-transfer-encoding",
        "mime-version",
        "date",
        "message-id",
    }
    for key, value in current.items():
        if key.casefold() not in skip:
            expected[key] = _header_text(value)

    from_value = normalize_text(expected.get("From", ""))
    domain = "andrewbaeten.nl"
    if "@" in from_value:
        domain = from_value.rsplit("@", 1)[-1].strip(" >") or domain
    expected["Date"] = formatdate(localtime=True)
    expected["Message-ID"] = make_msgid(domain=domain)
    expected.set_content(normalize_text(body))
    return expected


def _summary_base(mode: str, selected_count: int) -> dict:
    return {
        "mode": mode,
        "selected_count": selected_count,
        "automatic_send": False,
        "smtp_send": "not_available",
        "review_required_preserved": True,
    }


def build_audit(offset: int, limit: int) -> tuple[dict, dict]:
    if offset < 0 or not 1 <= limit <= MAX_REMEDIATION:
        raise ValueError(f"offset must be >=0 and limit must be 1-{MAX_REMEDIATION}")

    client = connect_imap()
    blockers: Counter[str] = Counter()
    items = []
    try:
        folder = find_drafts_folder(client)
        capability_tokens = imap_capability_tokens(client)
        pairs = growth_uid_index(client, folder)
        if len(pairs) < offset + limit:
            raise RuntimeError(
                f"Requested {limit} Growth drafts at offset {offset}, but only {len(pairs)} exist"
            )
        selected = pairs[offset:offset + limit]
        selected_messages = bulk_fetch_uid_messages(
            client,
            [uid for _lead_id, uid in selected],
        )
        replace_count = 0
        unchanged_count = 0
        tailored_count = 0
        fallback_count = 0
        legacy_value_count = 0

        for lead_id, uid in selected:
            msg = selected_messages[uid]
            before = full_snapshot(msg)
            reason = None
            analysis = None
            if before["lead_id"] != lead_id:
                reason = "lead_identity_mismatch"
            elif before["review_status"] != "contact-basis":
                reason = "not_review_required"
            elif msg.is_multipart():
                reason = "multipart_not_supported"
            else:
                try:
                    analysis = analyze_body(before["body"])
                except ValueError as exc:
                    reason = str(exc)

            if reason:
                blockers[reason] += 1
                items.append(
                    {
                        "lead_id": lead_id,
                        "uid_at_audit": uid.decode("ascii"),
                        "status": "blocker",
                        "reason": reason,
                        "before": before,
                    }
                )
                continue

            expected = snapshot_with_body(before, analysis["expected_body"])
            action = "replace" if expected != before else "unchanged"
            replace_count += int(action == "replace")
            unchanged_count += int(action == "unchanged")
            tailored_count += int(analysis["tailored"])
            fallback_count += int(not analysis["tailored"])
            legacy_value_count += int(
                not _valid_value_line(analysis["current_value"], analysis["language"])
            )
            items.append(
                {
                    "lead_id": lead_id,
                    "uid_at_audit": uid.decode("ascii"),
                    "status": "ready",
                    "action": action,
                    "language": analysis["language"],
                    "tailored": analysis["tailored"],
                    "before": before,
                    "expected": expected,
                }
            )

        now = int(time.time())
        state = {
            "version": STATE_VERSION,
            "created_at_epoch": now,
            "expires_at_epoch": now + STATE_TTL_SECONDS,
            "offset": offset,
            "limit": limit,
            "growth_total_at_audit": len(pairs),
            "items": items,
        }
        summary = {
            **_summary_base("audit", limit),
            "growth_total": len(pairs),
            "offset": offset,
            "replace_count": replace_count,
            "unchanged_count": unchanged_count,
            "tailored_expected_count": tailored_count,
            "fallback_expected_count": fallback_count,
            "legacy_value_count": legacy_value_count,
            "blocker_count": sum(blockers.values()),
            "blocker_reasons": dict(sorted(blockers.items())),
            "audit_eligible": not blockers,
            "uidplus_available": "UIDPLUS" in capability_tokens,
            "multiappend_available": "MULTIAPPEND" in capability_tokens,
            "read_only": True,
        }
        return state, summary
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _validate_state(state: dict) -> list[dict]:
    if state.get("version") != STATE_VERSION:
        raise ValueError("invalid audit state version")
    if int(state.get("expires_at_epoch") or 0) < int(time.time()):
        raise RuntimeError("audit state expired; run a fresh audit")
    items = state.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("audit state items missing")
    if any(item.get("status") != "ready" for item in items):
        raise RuntimeError("audit contains blockers; apply/final is not allowed")
    lead_ids = [str(item.get("lead_id") or "") for item in items]
    if len(set(lead_ids)) != len(lead_ids) or any(not LEAD_ID_RE.fullmatch(x) for x in lead_ids):
        raise RuntimeError("audit state has invalid or duplicate lead IDs")
    return items


def verify_or_apply(state: dict, mode: str) -> dict:
    if mode not in {"apply", "final"}:
        raise ValueError("mode must be apply or final")
    items = _validate_state(state)
    lead_ids = [item["lead_id"] for item in items]

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        if mode == "apply":
            require_uidplus(client, "value-sentence remediation")
        inventory = bulk_inventory_drafts(client, folder, lead_ids)
        pending = []
        already_expected = 0
        state_conflicts = 0

        for item in items:
            lead_id = item["lead_id"]
            current = current_from_inventory(inventory, lead_id)
            if current.get("count") != 1:
                state_conflicts += 1
                continue
            msg = inventory[lead_id]["messages"][0]
            current_full = full_snapshot(msg)
            if current_full == item["expected"]:
                already_expected += 1
            elif current_full == item["before"]:
                if mode == "apply" and item.get("action") == "replace":
                    pending.append(item)
                elif item.get("action") == "unchanged":
                    already_expected += 1
                else:
                    state_conflicts += 1
            else:
                state_conflicts += 1

        if state_conflicts:
            raise RuntimeError(
                f"{state_conflicts} audited drafts changed outside this remediation; no new mutation allowed"
            )
        if mode == "final" and pending:
            raise RuntimeError("final readback found drafts that still require replacement")

        changed = 0
        existing = already_expected
        if mode == "apply":
            for item in pending:
                lead_id = item["lead_id"]
                msg = inventory[lead_id]["messages"][0]
                if full_snapshot(msg) != item["before"]:
                    raise RuntimeError("draft changed after batch preflight; mutation blocked")
                expected_msg = message_with_body(msg, item["expected"]["body"])
                outcome, _uid, final_msg = replace_known_draft_and_verify(
                    client,
                    folder,
                    lead_id,
                    uid_from_inventory(inventory, lead_id),
                    expected_msg,
                    snapshot_message(msg, lead_id),
                )
                if full_snapshot(final_msg) != item["expected"]:
                    raise RuntimeError("full final draft readback mismatch")
                changed += int(outcome == "replaced")
                existing += int(outcome == "existing")

        final_inventory = bulk_inventory_drafts(client, folder, lead_ids)
        verified = 0
        for item in items:
            lead_id = item["lead_id"]
            current = current_from_inventory(final_inventory, lead_id)
            if current.get("count") != 1:
                raise RuntimeError("final inventory count mismatch")
            msg = final_inventory[lead_id]["messages"][0]
            if full_snapshot(msg) != item["expected"]:
                raise RuntimeError("independent final value-sentence readback mismatch")
            verified += 1

        return {
            **_summary_base(mode, len(items)),
            "changed_count": changed,
            "already_expected_count": existing,
            "verified_count": verified,
            "read_only": mode == "final",
            "readback": "exact",
        }
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("audit", "apply", "final"), required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=450)
    parser.add_argument("--audit-state")
    parser.add_argument("--state-output")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    secret = os.environ.get("OUTREACH_MAIL_PASSWORD", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "Yolol100/Leadscanner")

    if args.mode == "audit":
        if not args.state_output:
            raise SystemExit("--state-output is required for audit")
        state, summary = build_audit(args.offset, args.limit)
        envelope = encrypt_state(state, secret, repository)
        Path(args.state_output).write_text(
            json.dumps(envelope, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        if not args.audit_state:
            raise SystemExit("--audit-state is required for apply/final")
        envelope = json.loads(Path(args.audit_state).read_text(encoding="utf-8"))
        state = decrypt_state(envelope, secret, repository)
        summary = verify_or_apply(state, args.mode)

    Path(args.report).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "VALUE_SENTENCE_REMEDIATION=green "
        f"mode={summary['mode']} selected={summary['selected_count']} "
        f"changed={summary.get('changed_count', 0)} "
        f"verified={summary.get('verified_count', 0)} "
        f"blockers={summary.get('blocker_count', 0)} "
        "review_required=true automatic_send=false smtp_send=not_available"
    )
    if args.mode == "audit" and not summary.get("audit_eligible"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
