"""Private, evidence-led review of first-touch lead drafts. Never sends mail.

Input evidence must already be independently checked against the official website.
This deterministic gate cannot itself prove that supplied evidence is genuine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

OPT_OUT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
WEIGHTS = {
    "source_accuracy": 2.0,
    "activity_fit": 1.5,
    "distinctive_opening": 1.5,
    "added_value": 2.0,
    "natural_tone": 1.0,
    "subject_clarity": 1.0,
    "formal_requirements": 1.0,
}
DRAFT_ID = re.compile(r"^draft-[0-9a-f]{32}$")
GENERIC_OPENING = re.compile(
    r"^(ik kwam (jullie|de|uw) website|ik kwam jullie bedrijf|"
    r"op de website van .{0,100}(zag ik|las ik)|"
    r"ik kwam jullie website tegen|veel klanten ori[eë]nteren zich)", re.I
)
FEATURES = {
    "booking": ("online boeken", "boekingssysteem", "boekingsmogelijkheid", "afspraak boeken", "online afspraak"),
    "reservations": ("online reserveren", "reservatiesysteem", "reserveringssysteem", "reservering online"),
    "shop": ("webshop", "online bestellen", "online winkel"),
    "quote": ("offerteformulier", "offerte aanvragen", "offerteaanvraag"),
    "faq": ("veelgestelde vragen", "faq", "vraag en antwoord"),
}


def _host(url: str) -> str:
    try:
        parsed = urlsplit(str(url))
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme != "https" or not host or "." not in host or parsed.username:
            return ""
        return host
    except (ValueError, TypeError):
        return ""


def _same_site(a: str, b: str) -> bool:
    return bool(a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)))


def _feature_key(s: str) -> str:
    value = re.sub(r"\s+", " ", str(s).lower()).strip()
    for key, variants in FEATURES.items():
        if value == key or any(v in value for v in variants):
            return key
    return value


def _iso_recent(value: str, days: int = 30) -> bool:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
        return -300 <= age <= days * 86400
    except (ValueError, TypeError):
        return False


def _score_parts(parts: dict) -> tuple[dict, float]:
    if not isinstance(parts, dict) or set(parts) != set(WEIGHTS):
        raise ValueError("quality_rubric_fields_invalid")
    normalized = {}
    for key, maximum in WEIGHTS.items():
        value = parts[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("quality_rubric_value_invalid")
        if not 0 <= value <= maximum:
            raise ValueError("quality_rubric_out_of_range")
        normalized[key] = float(value)
    return normalized, round(sum(normalized.values()), 2)


def assess(record: dict) -> dict:
    """Return scores, explicit independent fact/copy states, and blocking reasons.

    Scores are editorial review inputs (not conversion measurements). Even a
    perfect score never authorizes sending; only human legal review can do so.
    """
    if not isinstance(record, dict):
        raise ValueError("quality_record_invalid")
    doc = record.get("draft") or {}
    ev = record.get("verification") or {}
    offer = record.get("proposal") or {}
    parts, raw = _score_parts(record.get("rubric"))
    if not isinstance(doc, dict) or not isinstance(ev, dict) or not isinstance(offer, dict):
        raise ValueError("quality_record_shape_invalid")
    if not DRAFT_ID.fullmatch(str(doc.get("draft_id", ""))):
        raise ValueError("quality_draft_id_invalid")

    subject = str(doc.get("subject", "")).strip()
    body = str(doc.get("body", "")).replace("\r\n", "\n").strip()
    email = str(doc.get("email", "")).lower().strip()
    website = _host(doc.get("source_url", ""))
    evidence_site = _host(ev.get("fact_source_url", ""))
    email_site = _host(ev.get("email_source_url", ""))
    errors = []
    def block(reason):
        if reason not in errors:
            errors.append(reason)

    if not website or not _same_site(website, evidence_site) or not _same_site(website, email_site):
        block("official_source_provenance_missing")
    if ev.get("company_identity") != "confirmed":
        block("company_identity_unconfirmed")
    if ev.get("branch") != "confirmed":
        block("branch_unconfirmed")
    if ev.get("email") != "confirmed" or email not in str(ev.get("email_source_excerpt", "")).lower():
        block("email_not_independently_confirmed")
    mail_domain = email.split("@")[-1] if email.count("@") == 1 else ""
    if not mail_domain or (not _same_site(website, mail_domain) and ev.get("cross_domain_link_proved") is not True):
        block("email_domain_association_unconfirmed")
    quote = str(ev.get("fact_quote", "")).strip()
    if (ev.get("fact") != "confirmed" or len(quote) < 5 or
            quote.casefold() not in str(ev.get("fact_source_excerpt", "")).casefold()):
        block("observed_fact_unconfirmed")
    if not _iso_recent(ev.get("checked_at", "")):
        block("source_check_missing_or_stale")
    if ev.get("dedupe") != "clear":
        block("historical_dedupe_not_clear")
    if ev.get("claims_supported") is not True:
        block("claims_not_supported")

    prior = {_feature_key(f) for f in ev.get("existing_features", []) if isinstance(f, str)}
    new_feature = _feature_key(offer.get("feature", ""))
    if not new_feature or new_feature in prior:
        block("already_existing_or_missing_feature")
    if not offer.get("adds_value") or len(str(offer.get("why_relevant", "")).strip()) < 12:
        block("added_value_not_established")

    if not subject or len(subject) > 100 or any(c in subject for c in "\r\n\x00"):
        block("subject_invalid")
    if not body or len(body.split()) > 110 or "\x00" in body:
        block("body_invalid_or_too_long")
    if "{{" in subject + body or "}}" in subject + body:
        block("template_placeholder_remaining")
    if body.count(OPT_OUT) != 1 or not body.endswith(OPT_OUT + "\n\nGroet,\nAndrew"):
        block("optout_or_signature_invalid")
    commercial = body.split(OPT_OUT, 1)[0]
    if commercial.count("?") != 1:
        block("commercial_cta_count_invalid")
    paragraphs = [p.strip() for p in commercial.split("\n\n") if p.strip()]
    opening = paragraphs[1] if len(paragraphs) > 1 else ""
    if not opening or GENERIC_OPENING.search(opening):
        block("generic_or_missing_opening")
    if "Ik ben Andrew van Webactueel".lower() in body.lower():
        block("unwanted_sender_introduction")
    if re.search(r"\b(gegarandeerd|100% meer|verdubbel(?:en|t)|altijd meer klanten)\b", body, re.I):
        block("unsupported_outcome_promise")

    factual_errors = {
        "official_source_provenance_missing", "company_identity_unconfirmed", "branch_unconfirmed",
        "email_not_independently_confirmed", "email_domain_association_unconfirmed",
        "observed_fact_unconfirmed", "source_check_missing_or_stale", "historical_dedupe_not_clear"
    }
    factually_confirmed = not any(x in factual_errors for x in errors)
    # Hard caps ensure high editorial ratings cannot mask fundamental problems.
    cap = 10.0
    if "company_identity_unconfirmed" in errors or "email_not_independently_confirmed" in errors:
        cap = min(cap, 3.5)
    if "branch_unconfirmed" in errors or "email_domain_association_unconfirmed" in errors:
        cap = min(cap, 4.0)
    if "observed_fact_unconfirmed" in errors or "official_source_provenance_missing" in errors or "source_check_missing_or_stale" in errors:
        cap = min(cap, 5.0)
    if "already_existing_or_missing_feature" in errors:
        cap = min(cap, 5.0)
    if "added_value_not_established" in errors:
        cap = min(cap, 6.0)
    if "historical_dedupe_not_clear" in errors or "claims_not_supported" in errors:
        cap = min(cap, 4.0)
    if "generic_or_missing_opening" in errors:
        cap = min(cap, 7.0)
    if any(x in errors for x in ("body_invalid_or_too_long", "optout_or_signature_invalid", "commercial_cta_count_invalid")):
        cap = 0.0

    overall = round(min(10.0, max(0.0, raw), cap), 2)
    factual_review_score = round(10 * (parts["source_accuracy"] + parts["activity_fit"]) / 3.5, 2)
    editorial_review_score = round(10 * (raw - parts["source_accuracy"] - parts["activity_fit"]) / 6.5, 2)
    strong = overall >= 8.5 and not errors and editorial_review_score >= 8.5
    return {
        "draft_id": doc["draft_id"],
        "score_0_to_10": overall,
        "factual_review_score_0_to_10": min(10.0, factual_review_score),
        "editorial_review_score_0_to_10": min(10.0, editorial_review_score),
        "factually_confirmed": factually_confirmed,
        "editorially_strong": strong,
        "additional_check_needed": bool(errors) or not strong,
        "not_send_ready": True,
        "eligible_for_private_draft": strong,
        "reasons": sorted(errors),
        "rewrite_guidance": sorted(errors),
        "measured_conversion": None,
        "human_legal_review_required": True,
    }


def improvement_stalled(before: dict, after: dict, round_index: int) -> bool:
    """Stop on no demonstrated gain or after two controlled rewrite rounds."""
    return (round_index >= 2 or
            after["score_0_to_10"] <= before["score_0_to_10"] + 0.1)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".quality-", dir=str(path.parent))
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        if _digest(path.read_bytes()) != _digest(raw):
            raise RuntimeError("quality_output_readback_mismatch")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _lines(rows: list[dict]) -> bytes:
    return ("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows)).encode()


def review_file(input_path: Path, output_path: Path, batch_size: int = 100) -> dict:
    """Checkpoint private reviews every 1..100 rows, fail closed on resume drift."""
    if not 1 <= batch_size <= 100 or input_path.resolve() == output_path.resolve():
        raise ValueError("quality_batch_request_invalid")
    source = input_path.read_bytes()
    records = [json.loads(line) for line in source.splitlines() if line.strip()]
    if not records:
        raise ValueError("quality_empty_input")
    ids = [r.get("draft", {}).get("draft_id") for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("quality_duplicate_input_ids")
    input_sha = _digest(source)
    state_path = Path(str(output_path) + ".checkpoint.json")
    saved: list[dict] = []
    if output_path.exists() != state_path.exists():
        raise RuntimeError("quality_partial_checkpoint_detected")
    if state_path.exists():
        state = json.loads(state_path.read_text())
        saved = [json.loads(line) for line in output_path.read_bytes().splitlines() if line.strip()]
        if (state.get("input_sha256") != input_sha or
            state.get("output_sha256") != _digest(output_path.read_bytes()) or
            state.get("completed") != len(saved)):
            raise RuntimeError("quality_checkpoint_drift")
        for index, row in enumerate(saved):
            expected = _digest(_lines([records[index]]))
            if row.get("input_sha256") != expected or row.get("draft_id") != ids[index]:
                raise RuntimeError("quality_checkpoint_content_mismatch")
    for start in range(len(saved), len(records), batch_size):
        batch = []
        for record in records[start:start + batch_size]:
            result = assess(record)
            result["input_sha256"] = _digest(_lines([record]))
            batch.append(result)
        saved.extend(batch)
        output_bytes = _lines(saved)
        _atomic_write(output_path, output_bytes)
        _atomic_write(state_path, _lines([{
            "input_sha256": input_sha, "completed": len(saved),
            "output_sha256": _digest(output_bytes), "batch_size": batch_size,
        }]))
    return {"requested": len(records), "reviewed": len(saved),
            "eligible_for_private_draft": sum(bool(x["eligible_for_private_draft"]) for x in saved),
            "blocked_or_rewrite": sum(not x["eligible_for_private_draft"] for x in saved),
            "input_sha256": input_sha, "output_sha256": _digest(output_path.read_bytes())}


def main() -> None:
    parser = argparse.ArgumentParser(description="Private pre-draft quality review; never sends mail")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(review_file(args.input, args.output, args.batch_size), sort_keys=True))


if __name__ == "__main__":
    main()
