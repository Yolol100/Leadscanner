"""Bounded opening-only repair, with immutable audits and exact mailbox readback."""
from __future__ import annotations

import argparse
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from myhost_content_remediation import load_source_rows
from myhost_draft import build_message, connect_imap, find_drafts_folder
from myhost_fast_mailbox import (
    bulk_inventory_drafts,
    current_from_inventory,
    delete_known_draft_and_verify,
    replace_known_draft_and_verify,
    snapshot_message,
    uid_from_inventory,
)
from opening_fastpath import DEFAULT_SHARD_CONCURRENCY, audit_websites


DEFAULT_AUDIT_TTL_SECONDS = 6 * 60 * 60
MAX_SINGLE_RUN = 100
MAX_BULK_RUN = 500


def _website_workers(count: int) -> int:
    """Compatibility helper: report the bounded async shard concurrency."""
    if count <= 0:
        return 1
    raw = os.environ.get("LEADSCANNER_WEBSITE_SHARD_CONCURRENCY", str(DEFAULT_SHARD_CONCURRENCY))
    try:
        requested = int(raw)
    except (TypeError, ValueError):
        requested = DEFAULT_SHARD_CONCURRENCY
    return max(1, min(count, 80, requested))


def _audit_ttl_seconds() -> int:
    try:
        value = int(os.environ.get("LEADSCANNER_OPENING_AUDIT_TTL_SECONDS", str(DEFAULT_AUDIT_TTL_SECONDS)))
    except (TypeError, ValueError):
        value = DEFAULT_AUDIT_TTL_SECONDS
    return max(60, min(24 * 60 * 60, value))


def _parse_verified_at(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def website_result_is_fresh(result: dict, *, now: datetime | None = None) -> bool:
    if not isinstance(result, dict) or result.get("status") not in {"ready", "hold"}:
        return False
    verified = _parse_verified_at(result.get("verified_at"))
    if verified is None:
        return False
    current = now or datetime.now(timezone.utc)
    age = (current - verified).total_seconds()
    return 0 <= age <= _audit_ttl_seconds()


def website_audit(row, override=None):
    """Single-row compatibility route backed by the async auditor."""
    return audit_websites([row], [override])[0]


def validate_request(req):
    allowed = {
        "mode", "source_archive_artifact_id", "source_artifact_ids", "offset", "limit",
        "audit_artifact_id", "observations", "holds", "orchestrator", "shard_size",
    }
    if not isinstance(req, dict) or set(req) - allowed:
        raise ValueError("unsupported opening-remediation fields")
    if req.get("mode") not in {"audit", "apply", "final"}:
        raise ValueError("mode must be audit, apply or final")
    if type(req.get("offset")) is not int or req["offset"] < 0:
        raise ValueError("invalid offset")
    bulk = req.get("orchestrator") is True
    maximum = MAX_BULK_RUN if bulk else MAX_SINGLE_RUN
    if type(req.get("limit")) is not int or not 1 <= req["limit"] <= maximum:
        raise ValueError(f"limit must be 1-{maximum}")
    if bulk:
        shard_size = req.get("shard_size", 90)
        if type(shard_size) is not int or not 1 <= shard_size <= MAX_SINGLE_RUN:
            raise ValueError("shard_size must be 1-100")
    elif req.get("shard_size") is not None:
        raise ValueError("shard_size requires orchestrator=true")
    if type(req.get("source_archive_artifact_id")) is not int or req["source_archive_artifact_id"] <= 0:
        raise ValueError("positive source archive required")
    aids = req.get("source_artifact_ids")
    if not isinstance(aids, list) or not 1 <= len(aids) <= 20 or any(type(x) is not int or x <= 0 for x in aids) or len(set(aids)) != len(aids):
        raise ValueError("invalid ordered source artifact IDs")
    if req.get("mode") != "audit" and (type(req.get("audit_artifact_id")) is not int or req["audit_artifact_id"] <= 0):
        raise ValueError("immutable audit required")
    if req.get("mode") == "audit" and req.get("observations"):
        raise ValueError("initial audit cannot override observations")
    return req


def opening_span(body):
    match = re.match(r"\A(?:Hallo,|Goedendag,|Hello,)\n\n([^\n]+)(?=\n\n)", body)
    if not match:
        raise ValueError("unsupported existing greeting/opening layout")
    return match.span(1)


def replace_opening(body, opening):
    start, end = opening_span(body)
    return body[:start] + opening + body[end:]


def correct_company_placeholders(body, subject, proof):
    new = proof.get("company_name")
    if not new:
        return body, subject
    old = proof.get("old_company_name")
    if not old or not new.strip() or "\n" in old + new or len(new) > 120:
        raise ValueError("invalid proven company-name correction")
    old_cta = f"Zal ik vrijblijvend een voorbeeld design maken voor {old}?"
    new_cta = f"Zal ik vrijblijvend een voorbeeld design maken voor {new}?"
    if subject not in {f"Idee voor {old}", f"Idee voor {new}"}:
        raise ValueError("company correction subject does not match audited identity")
    if body.count(old_cta) == 1:
        body = body.replace(old_cta, new_cta, 1)
    elif body.count(new_cta) != 1:
        raise ValueError("company correction CTA does not match audited identity")
    return body, f"Idee voor {new}"


def source_selection(req, source_root):
    rows = list(load_source_rows(source_root, req["source_artifact_ids"]).values())
    selected = rows[req["offset"]:req["offset"] + req["limit"]]
    if len(selected) != req["limit"]:
        raise ValueError("source slice incomplete")
    return selected


def _resolve_website_results(rows, req, audit, precomputed=None):
    mode = req["mode"]
    if precomputed is not None:
        values = list(precomputed)
        if len(values) != len(rows):
            raise ValueError("precomputed website result count mismatch")
        return values, {"network_rows": 0, "reused_rows": len(values), "final_mailbox_only": mode == "final"}
    if mode == "audit":
        return audit_websites(rows), {"network_rows": len(rows), "reused_rows": 0, "final_mailbox_only": False}
    if audit is None:
        raise ValueError("immutable audit is required")
    if mode == "final":
        values = []
        for index, row in enumerate(rows):
            baseline = audit["items"][index]
            if baseline.get("lead_id") != row["lead_id"]:
                raise ValueError("audit order mismatch")
            website = deepcopy(baseline.get("website") or {})
            if website.get("status") not in {"ready", "hold"}:
                raise ValueError("final requires audited website decision")
            values.append(website)
        return values, {"network_rows": 0, "reused_rows": len(values), "final_mailbox_only": True}

    overrides = req.get("observations") or {}
    values: list[dict | None] = [None] * len(rows)
    refresh_rows = []
    refresh_proofs = []
    refresh_indexes = []
    reused = 0
    for index, row in enumerate(rows):
        baseline = audit["items"][index]
        if baseline.get("lead_id") != row["lead_id"]:
            raise ValueError("audit order mismatch")
        lead_id = row["lead_id"]
        override = overrides.get(lead_id)
        baseline_website = deepcopy(baseline.get("website") or {})
        if override:
            refresh_indexes.append(index)
            refresh_rows.append(row)
            refresh_proofs.append(override)
        elif website_result_is_fresh(baseline_website):
            values[index] = baseline_website
            reused += 1
        else:
            refresh_indexes.append(index)
            refresh_rows.append(row)
            refresh_proofs.append(None)
    if refresh_rows:
        refreshed = audit_websites(refresh_rows, refresh_proofs)
        for index, result in zip(refresh_indexes, refreshed):
            values[index] = result
    if any(value is None for value in values):
        raise ValueError("website result resolution incomplete")
    return list(values), {
        "network_rows": len(refresh_rows),
        "reused_rows": reused,
        "final_mailbox_only": False,
    }


def run(req, source_root, audit=None, *, precomputed_website_results=None):
    req = validate_request(req)
    if req.get("orchestrator"):
        raise ValueError("orchestrator requests require myhost_opening_bulk.py")
    rows = source_selection(req, source_root)
    ids = [r["lead_id"] for r in rows]
    if (set(req.get("observations") or {}) | set(req.get("holds") or {})) - set(ids):
        raise ValueError("decision escaped source slice")
    if set(req.get("observations") or {}) & set(req.get("holds") or {}):
        raise ValueError("ambiguous ready/hold decision")
    if audit and (audit.get("lead_ids") != ids or audit.get("source_artifact_ids") != req["source_artifact_ids"]):
        raise ValueError("immutable audit/source scope mismatch")

    mode = req["mode"]
    website_results, website_stats = _resolve_website_results(
        rows, req, audit, precomputed=precomputed_website_results
    )
    report = {
        "mode": mode,
        "lead_ids": ids,
        "source_artifact_ids": req["source_artifact_ids"],
        "offset": req["offset"],
        "audited_count": len(rows),
        "automatic_send": False,
        "send_capability": "unavailable",
        "read_only": mode != "apply",
        "items": [],
        "website_workers": _website_workers(len(rows)),
        "website_network_rows": website_stats["network_rows"],
        "website_reused_rows": website_stats["reused_rows"],
        "final_mailbox_only": website_stats["final_mailbox_only"],
        "audit_ttl_seconds": _audit_ttl_seconds(),
    }

    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        report["draft_folder"] = folder
        inventory = bulk_inventory_drafts(client, folder, ids)
        for index, row in enumerate(rows):
            lead_id = row["lead_id"]
            item = {"lead_id": lead_id, "company": row.get("company"), "changed": False, "removed": 0}
            try:
                current = current_from_inventory(inventory, lead_id)
                uid = uid_from_inventory(inventory, lead_id)
                item["before"] = current
                item["website"] = deepcopy(website_results[index])

                if mode == "audit":
                    item["status"] = "absent" if current["count"] == 0 else item["website"]["status"]
                    if current["count"] not in {0, 1}:
                        item.update(status="hold", reason="ambiguous duplicate draft identity")
                    elif current["count"] == 1:
                        if current["actual_lead_id"] != lead_id or current["to"].casefold() != row["email"].casefold() or current["review_status"] != "contact-basis":
                            item.update(status="hold", reason="current draft source identity or review status mismatch")
                        else:
                            start, end = opening_span(current["body"])
                            item["old_opening"] = current["body"][start:end]
                    item["after"] = current

                else:
                    baseline = audit["items"][index]
                    if baseline["lead_id"] != lead_id:
                        raise ValueError("audit order mismatch")
                    if mode == "apply" and current != baseline["before"]:
                        raise ValueError("draft changed since read-only audit; no mutation allowed")

                    hold_reason = (req.get("holds") or {}).get(lead_id)
                    if hold_reason:
                        item["website"].update(status="hold", reason=hold_reason)

                    if current["count"] == 0:
                        if mode == "final" and item["website"].get("status") == "ready":
                            raise ValueError("ready draft is absent during final readback")
                        item["status"] = "hold" if mode == "final" and item["website"].get("status") == "hold" else "absent"
                        if item["status"] == "hold":
                            item["reason"] = item["website"].get("reason")
                        item["after"] = current
                    elif current["count"] != 1 or current.get("actual_lead_id") != lead_id or current.get("review_status") != "contact-basis" or current.get("to", "").casefold() != row["email"].casefold():
                        raise ValueError("ambiguous or mismatched draft identity; mutation blocked")
                    elif item["website"].get("status") == "hold":
                        item.update(status="hold", reason=item["website"].get("reason") or "official proof unavailable")
                        if mode == "apply":
                            item["removed"] = delete_known_draft_and_verify(
                                client, folder, lead_id, uid, current
                            )
                            item["after"] = {"lead_id": lead_id, "count": 0, "duplicate": False}
                        else:
                            item["after"] = current
                            raise ValueError("hold draft remains during final readback")
                    else:
                        proof = item["website"].get("proof") or {}
                        opening = proof.get("opening")
                        if not opening:
                            raise ValueError("ready website decision lacks proven opening")
                        body = replace_opening(current["body"], opening)
                        body, subject = correct_company_placeholders(body, current["subject"], proof)
                        if mode == "final":
                            if body != current["body"] or subject != current["subject"]:
                                raise ValueError("ready draft opening does not match audited official proof")
                            item["status"] = "ready"
                            item["after"] = current
                        else:
                            new_row = {
                                "lead_id": lead_id,
                                "email": current["to"],
                                "subject": subject,
                                "body": body,
                                "status": "review_draft",
                                "contact_basis_status": "review_required",
                            }
                            _, expected = build_message(new_row)
                            outcome, final_uid, final_msg = replace_known_draft_and_verify(
                                client, folder, lead_id, uid, expected, current
                            )
                            item["outcome"] = outcome
                            item["changed"] = outcome == "replaced"
                            item["status"] = "ready"
                            item["after"] = snapshot_message(final_msg, lead_id)
                            item["final_uid"] = final_uid.decode("ascii")
                        item["new_opening"] = opening

                if mode != "audit" and item.get("status") == "ready":
                    after = item["after"]
                    if after["count"] != 1 or after["duplicate"] or after["review_status"] != "contact-basis" or after["to"] != current["to"] or after["subject"] != subject or after["body"] != body:
                        raise ValueError("full final mailbox readback mismatch")
                if mode == "apply" and item.get("status") in {"hold", "absent"} and item["after"]["count"] != 0:
                    raise ValueError("unproven hold draft remains; closure blocked")
            except Exception as exc:
                item.update(status="hold", blocker=f"{type(exc).__name__}: {exc}")
            report["items"].append(item)
            print(
                f"OPENING_LEAD={lead_id} status={item['status']} changed={str(item['changed']).lower()}",
                flush=True,
            )

        for status in ("ready", "hold", "absent"):
            report[status + "_count"] = sum(i["status"] == status for i in report["items"])
        report["changed_count"] = sum(i["changed"] for i in report["items"])
        report["already_correct_count"] = sum(i.get("outcome") == "existing" for i in report["items"])
        report["removed_count"] = sum(i["removed"] for i in report["items"])
        report["blockers"] = [
            {"lead_id": i["lead_id"], "reason": i["blocker"]}
            for i in report["items"] if i.get("blocker")
        ]
        return report
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--audit")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    audit = json.loads(Path(args.audit).read_text()) if args.audit else None
    req = json.loads(Path(args.request).read_text())
    report = run(req, Path(args.source_root), audit)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"OPENING_REMEDIATION=green mode={report['mode']} audited={report['audited_count']} "
        f"ready={report['ready_count']} hold={report['hold_count']} absent={report['absent_count']} "
        f"changed={report['changed_count']} website_network_rows={report['website_network_rows']} "
        f"website_reused_rows={report['website_reused_rows']} final_mailbox_only={str(report['final_mailbox_only']).lower()} "
        "automatic_send=false send_capability=unavailable"
    )
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
