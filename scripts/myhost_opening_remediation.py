"""Bounded opening-only repair, with immutable audits and exact mailbox readback."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from urllib.parse import urljoin

import requests
from extract_public_contacts import LinkParser, detect_language, fetch_html, normalize_domain
from myhost_content_remediation import load_source_rows
from myhost_draft import (build_message, connect_imap, exact_message_matches, fetch_message,
    find_drafts_folder, find_message_ids, normalize_text, plain_body, require_existing_drafts,
    append_and_verify, select_folder)
from myhost_remove_hold_draft import remove_hold_draft
from observation_quality import business_sentences, first_party_prose, natural_opening


DEFAULT_WEBSITE_WORKERS = 20
MAX_WEBSITE_WORKERS = 24


def _website_workers(count: int) -> int:
    if count <= 0:
        return 1
    raw = os.environ.get("LEADSCANNER_WEBSITE_WORKERS", str(DEFAULT_WEBSITE_WORKERS))
    try:
        requested = int(raw)
    except (TypeError, ValueError):
        requested = DEFAULT_WEBSITE_WORKERS
    return max(1, min(count, MAX_WEBSITE_WORKERS, requested))


def _website_audit_job(args):
    row, proof = args
    return website_audit(row, proof)


def audit_websites(rows, proofs=None):
    rows = list(rows)
    if proofs is None:
        proofs = [None] * len(rows)
    else:
        proofs = list(proofs)
    if len(proofs) != len(rows):
        raise ValueError("website proof count mismatch")
    if not rows:
        return []
    workers = _website_workers(len(rows))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_website_audit_job, zip(rows, proofs)))


def validate_request(req):
    allowed = {"mode", "source_archive_artifact_id", "source_artifact_ids", "offset", "limit", "audit_artifact_id", "observations"}
    if not isinstance(req, dict) or set(req) - allowed:
        raise ValueError("unsupported opening-remediation fields")
    if req.get("mode") not in {"audit", "apply", "final"}:
        raise ValueError("mode must be audit, apply or final")
    if type(req.get("offset")) is not int or req["offset"] < 0:
        raise ValueError("invalid offset")
    if type(req.get("limit")) is not int or not 1 <= req["limit"] <= 100:
        raise ValueError("limit must be 1-100")
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
    # Preserve every character outside the factual opening paragraph.
    match = re.match(r"\A(?:Hallo,|Goedendag,|Hello,)\n\n([^\n]+)(?=\n\n)", body)
    if not match:
        raise ValueError("unsupported existing greeting/opening layout")
    return match.span(1)


def replace_opening(body, opening):
    start, end = opening_span(body)
    return body[:start] + opening + body[end:]


def snapshot(msg, lead_id):
    return {"lead_id": lead_id, "to": normalize_text(msg.get("To", "")),
        "subject": normalize_text(msg.get("Subject", "")), "body": plain_body(msg),
        "review_status": normalize_text(msg.get("X-Webactueel-Review-Required", "")),
        "actual_lead_id": normalize_text(msg.get("X-Webactueel-Lead-ID", ""))}


def read_current(client, folder, lead_id):
    ids = find_message_ids(client, folder, lead_id)
    if len(ids) != 1:
        return {"lead_id": lead_id, "count": len(ids), "duplicate": len(ids) > 1}
    return {**snapshot(fetch_message(client, ids[0]), lead_id), "count": 1, "duplicate": False}


def website_audit(row, override=None):
    expected = normalize_domain(row.get("website") or "")
    urls = [str(row.get("website") or "")]
    override = override or {}
    if override.get("source_url"):
        urls.append(override["source_url"])
    session = requests.Session()
    pages = []
    errors = []
    candidates = []
    for url in urls:
        if len(pages) >= 3:
            break
        if normalize_domain(url) != expected:
            errors.append("official_domain_mismatch")
            continue
        try:
            html, final, status = fetch_html(session, url)
            if not html or not final or not status or not 200 <= status < 400:
                errors.append(f"{url}: HTTP {status or 'unavailable'}; no readable official page")
                continue
            if normalize_domain(final) != expected:
                errors.append(f"{url}: redirected off official domain")
                continue
            lang, _ = detect_language(html, default=row.get("language") or "nl")
            blocks = first_party_prose(html)
            sentences = business_sentences(html)
            pages.append({"url": final, "http_status": status, "language": lang,
                "sha256": hashlib.sha256(html.encode()).hexdigest(), "prose": blocks[:100]})
            for sentence in sentences:
                try:
                    opening = natural_opening(sentence, lang)
                    # Automated facts must describe the business itself, not a
                    # partner, reviewer or named third party on its website.
                    if not re.match(r"^(Wij|We|Jullie)\b", sentence):
                        continue
                    candidates.append({"observation": sentence, "opening": opening, "source_url": final, "language": lang})
                except ValueError:
                    pass
            if len(pages) == 1:
                parser = LinkParser(); parser.feed(html)
                for href, label in parser.links:
                    link = urljoin(final, href)
                    if normalize_domain(link) == expected and re.search(r"over.?ons|about|diensten|services|producten|products|assortiment|menu|menukaart", link + " " + label, re.I) and link not in urls:
                        urls.append(link)
                        if len(urls) >= 6:
                            break
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    if override:
        observation = str(override.get("observation") or "")
        for page in pages:
            if page["url"] == override.get("source_url") and any(observation in b for b in page["prose"]):
                try:
                    return {"status": "ready", "proof": {"observation": observation,
                        "opening": natural_opening(observation, page["language"]),
                        "source_url": page["url"], "language": page["language"]}, "pages": pages, "errors": errors}
                except ValueError as exc:
                    errors.append(str(exc))
        errors.append("exact approved business sentence absent from eligible first-party prose")
    elif candidates:
        return {"status": "ready", "proof": candidates[0], "pages": pages, "errors": errors}
    return {"status": "hold", "reason": "; ".join(errors) if not pages else
        "No short declarative business fact with an explicit business subject could be verified in eligible prose on the checked official pages; " + "; ".join(errors), "pages": pages, "errors": errors}


def source_selection(req, source_root):
    rows = list(load_source_rows(source_root, req["source_artifact_ids"]).values())
    selected = rows[req["offset"]:req["offset"] + req["limit"]]
    if len(selected) != req["limit"]:
        raise ValueError("source slice incomplete")
    return selected


def run(req, source_root, audit=None):
    req = validate_request(req)
    rows = source_selection(req, source_root)
    ids = [r["lead_id"] for r in rows]
    if audit and (audit.get("lead_ids") != ids or audit.get("source_artifact_ids") != req["source_artifact_ids"]):
        raise ValueError("immutable audit/source scope mismatch")
    mode = req["mode"]
    report = {"mode": mode, "lead_ids": ids, "source_artifact_ids": req["source_artifact_ids"],
        "offset": req["offset"], "audited_count": len(rows), "automatic_send": False,
        "send_capability": "unavailable", "read_only": mode != "apply", "items": [],
        "website_workers": _website_workers(len(rows))}
    if mode == "audit":
        website_results = audit_websites(rows)
    else:
        proofs = []
        overrides = req.get("observations") or {}
        for index, row in enumerate(rows):
            baseline = audit["items"][index]
            if baseline["lead_id"] != row["lead_id"]:
                raise ValueError("audit order mismatch")
            proofs.append(
                overrides.get(row["lead_id"])
                or baseline.get("website", {}).get("proof")
            )
        # Revalidate all current first-party evidence before touching IMAP.
        # Network I/O is independent and safe to parallelize; mailbox mutation is not.
        website_results = audit_websites(rows, proofs)
    client = connect_imap()
    try:
        folder = find_drafts_folder(client)
        report["draft_folder"] = folder
        for index, row in enumerate(rows):
            lead_id = row["lead_id"]
            item = {"lead_id": lead_id, "company": row.get("company"), "changed": False, "removed": 0}
            try:
                current = read_current(client, folder, lead_id)
                item["before"] = current
                if mode == "audit":
                    item["website"] = website_results[index]
                    item["status"] = "absent" if current["count"] == 0 else item["website"]["status"]
                    if current["count"] != 1 and current["count"] != 0:
                        item.update(status="hold", reason="ambiguous duplicate draft identity")
                    elif current["count"] == 1:
                        if current["actual_lead_id"] != lead_id or current["to"].casefold() != row["email"].casefold() or current["review_status"] != "contact-basis":
                            item.update(status="hold", reason="current draft source identity or review status mismatch")
                        else:
                            start, end = opening_span(current["body"])
                            item["old_opening"] = current["body"][start:end]
                else:
                    baseline = audit["items"][index]
                    if baseline["lead_id"] != lead_id:
                        raise ValueError("audit order mismatch")
                    if mode == "apply" and current != baseline["before"]:
                        raise ValueError("draft changed since read-only audit; no mutation allowed")
                    item["website"] = website_results[index]
                    if current["count"] == 0:
                        item["status"] = "absent"
                    elif current["count"] != 1 or current.get("actual_lead_id") != lead_id or current.get("review_status") != "contact-basis" or current.get("to", "").casefold() != row["email"].casefold():
                        raise ValueError("ambiguous or mismatched draft identity; mutation blocked")
                    elif item["website"]["status"] == "hold":
                        item.update(status="hold", reason=item["website"]["reason"])
                        if mode == "apply":
                            item["removed"] = remove_hold_draft(lead_id, expected_snapshot=current)["removed_count"]
                    else:
                        opening = item["website"]["proof"]["opening"]
                        body = replace_opening(current["body"], opening)
                        if mode == "final":
                            if body != current["body"]:
                                raise ValueError("ready draft opening does not match current official proof")
                            item["status"] = "ready"
                        else:
                            new_row = {"lead_id": lead_id, "email": current["to"], "subject": current["subject"],
                                "body": body, "status": "review_draft", "contact_basis_status": "review_required"}
                            _, expected = build_message(new_row)
                            require_existing_drafts(client, folder, [(new_row, lead_id, expected)])
                            if read_current(client, folder, lead_id) != current:
                                raise ValueError("draft changed immediately before bounded replacement")
                            item["outcome"] = append_and_verify(client, folder, lead_id, expected)
                            item["changed"] = item["outcome"] == "replaced"
                            item["status"] = "ready"
                        item["new_opening"] = opening
                item["after"] = read_current(client, folder, lead_id)
                if mode != "audit" and item["status"] == "ready":
                    after = item["after"]
                    if after["count"] != 1 or after["duplicate"] or after["review_status"] != "contact-basis" or after["to"] != current["to"] or after["subject"] != current["subject"] or after["body"] != body:
                        raise ValueError("full final mailbox readback mismatch")
                if mode == "apply" and item["status"] in {"hold", "absent"} and item["after"]["count"] != 0:
                    raise ValueError("unproven hold draft remains; closure blocked")
            except Exception as exc:
                item.update(status="hold", blocker=f"{type(exc).__name__}: {exc}")
                # No speculative retry after an uncertain write.
            report["items"].append(item)
            print(f"OPENING_LEAD={lead_id} status={item['status']} changed={str(item['changed']).lower()}", flush=True)
        for status in ("ready", "hold", "absent"):
            report[status + "_count"] = sum(i["status"] == status for i in report["items"])
        report["changed_count"] = sum(i["changed"] for i in report["items"])
        report["already_correct_count"] = sum(i.get("outcome") == "existing" for i in report["items"])
        report["removed_count"] = sum(i["removed"] for i in report["items"])
        report["blockers"] = [{"lead_id": i["lead_id"], "reason": i["blocker"]} for i in report["items"] if i.get("blocker")]
        return report
    finally:
        client.logout()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--audit")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    audit = json.loads(Path(args.audit).read_text()) if args.audit else None
    report = run(json.loads(Path(args.request).read_text()), Path(args.source_root), audit)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"OPENING_REMEDIATION=green mode={report['mode']} audited={report['audited_count']} ready={report['ready_count']} hold={report['hold_count']} absent={report['absent_count']} changed={report['changed_count']} website_workers={report['website_workers']} automatic_send=false send_capability=unavailable")
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
