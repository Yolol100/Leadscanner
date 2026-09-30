from __future__ import annotations

import json
import zipfile
from pathlib import Path

from myhost_draft import normalize_text, plain_body


SCHEMA_VERSION = "webactueel-invalid-draft-baselines/1.0"


def _normalized_version(version: dict) -> dict:
    result = {
        "to": normalize_text(version.get("to")),
        "subject": normalize_text(version.get("subject")),
        "body": normalize_text(version.get("body")),
        "review_status": normalize_text(version.get("review_status")),
    }
    if not all(result.values()):
        raise ValueError("expected draft version is incomplete")
    if result["review_status"] != "contact-basis":
        raise ValueError("expected version is not marked review_required")
    return result


def version_matches_message(actual, lead_id: str, version: dict) -> bool:
    expected = _normalized_version(version)
    return (
        normalize_text(actual.get("X-Webactueel-Lead-ID", "")) == lead_id
        and normalize_text(actual.get("To", "")) == expected["to"]
        and normalize_text(actual.get("Subject", "")) == expected["subject"]
        and normalize_text(actual.get("X-Webactueel-Review-Required", ""))
        == expected["review_status"]
        and plain_body(actual) == expected["body"]
    )


def build_expected_versions(
    source_rows: dict[str, dict],
    previous_versions: dict[str, dict],
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for lead_id, row in source_rows.items():
        if row.get("lead_id") != lead_id:
            raise ValueError(f"{lead_id}: source row identity mismatch")
        if row.get("status") != "review_draft" or row.get("contact_basis_status") != "review_required":
            raise ValueError(f"{lead_id}: source row is not a review_required review_draft")
        source_version = _normalized_version(
            {
                "to": row.get("email"),
                "subject": row.get("subject"),
                "body": row.get("body"),
                "review_status": "contact-basis",
            }
        )
        versions = [source_version]
        previous = previous_versions.get(lead_id)
        if previous:
            previous = _normalized_version(previous)
            if previous["to"] != source_version["to"]:
                raise ValueError(f"{lead_id}: previous successful readback changed the recipient")
            if previous not in versions:
                versions.append(previous)
        result[lead_id] = {
            "expected_versions": versions,
            "provenance": [
                "source_artifact",
                *(
                    ["previous_successful_exact_readback"]
                    if len(versions) > 1
                    else []
                ),
            ],
        }
    return result


def load_previous_exact_versions(archive_path: str | Path, lead_ids: set[str]) -> dict[str, dict]:
    path = Path(archive_path)
    if not path.exists():
        return {}

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        audit_names = sorted(
            name
            for name in names
            if name.startswith("final-audit-") and name.endswith(".json")
        )
        if not audit_names:
            raise ValueError("previous successful artifact has no final audit")

        audited_total = 0
        for name in audit_names:
            audit = json.loads(archive.read(name))
            requested = int(audit.get("requested_total") or 0)
            if (
                requested <= 0
                or audit.get("artifact_rows") != requested
                or audit.get("artifact_readbacks") != requested
                or audit.get("unique_lead_ids") != requested
                or audit.get("unique_emails") != requested
                or audit.get("unique_domains") != requested
                or audit.get("final_set_current_expected") != requested
                or audit.get("final_set_current_exact_matches") != requested
                or audit.get("failure_count") != 0
                or audit.get("failures") != []
                or audit.get("read_only") is not True
                or audit.get("automatic_send") is not False
                or audit.get("smtp_send") != "not_available"
            ):
                raise ValueError(f"previous final audit is not an exact no-send pass: {name}")
            audited_total += requested

        report_names = sorted(
            name
            for name in names
            if name.startswith("rewrite/") and name.endswith("/myhost-drafts.json")
        )
        if not report_names:
            raise ValueError("previous successful artifact has no exact draft readbacks")

        versions: dict[str, dict] = {}
        report_total = 0
        for name in report_names:
            report = json.loads(archive.read(name))
            eligible = int(report.get("eligible_count") or 0)
            items = report.get("items") or []
            if (
                len(items) != eligible
                or int(report.get("created_count") or 0) != 0
                or int(report.get("existing_count") or 0)
                + int(report.get("replaced_count") or 0)
                != eligible
                or int(report.get("review_required_count") or 0) != eligible
                or report.get("smtp_send") != "not_available"
            ):
                raise ValueError(f"previous draft readback is incomplete: {name}")
            report_total += eligible
            for item in items:
                lead_id = normalize_text(item.get("lead_id"))
                if lead_id not in lead_ids:
                    continue
                if lead_id in versions:
                    raise ValueError(f"{lead_id}: duplicate in previous exact readback")
                if item.get("outcome") not in {"existing", "replaced"}:
                    raise ValueError(f"{lead_id}: previous outcome is not an existing/replaced draft")
                versions[lead_id] = _normalized_version(item)

        if report_total != audited_total:
            raise ValueError("previous draft readback total does not match final audit total")
        return versions


def load_expected_versions(path: str | Path, lead_id: str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") == SCHEMA_VERSION:
        row = (payload.get("lead_ids") or {}).get(lead_id)
        if not row:
            raise ValueError(f"{lead_id}: exact expected versions are missing")
        versions = row.get("expected_versions") or []
    else:
        if (
            payload.get("lead_id") != lead_id
            or payload.get("status") != "review_draft"
            or payload.get("contact_basis_status") != "review_required"
        ):
            raise ValueError(f"{lead_id}: source-row identity or review status mismatch")
        versions = [
            {
                "to": payload.get("email"),
                "subject": payload.get("subject"),
                "body": payload.get("body"),
                "review_status": "contact-basis",
            }
        ]
    return [_normalized_version(version) for version in versions]
