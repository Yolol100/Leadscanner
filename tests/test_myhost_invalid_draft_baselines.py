from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from myhost_invalid_draft_baselines import (
    SCHEMA_VERSION,
    build_expected_versions,
    load_expected_versions,
    load_previous_exact_versions,
)


LEAD_ID = "growth-0123456789abcdefabcd"


def _archive(path: Path, *, to: str = "info@example.nl", failures: list | None = None) -> None:
    audit = {
        "requested_total": 1,
        "artifact_rows": 1,
        "artifact_readbacks": 1,
        "unique_lead_ids": 1,
        "unique_emails": 1,
        "unique_domains": 1,
        "final_set_current_expected": 1,
        "final_set_current_exact_matches": 1,
        "failure_count": len(failures or []),
        "failures": failures or [],
        "read_only": True,
        "automatic_send": False,
        "smtp_send": "not_available",
    }
    report = {
        "eligible_count": 1,
        "created_count": 0,
        "existing_count": 0,
        "replaced_count": 1,
        "review_required_count": 1,
        "smtp_send": "not_available",
        "items": [{
            "lead_id": LEAD_ID,
            "to": to,
            "subject": "New subject",
            "body": "New body",
            "review_status": "contact-basis",
            "outcome": "replaced",
        }],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("final-audit-a.json", json.dumps(audit))
        archive.writestr("rewrite/1/myhost-drafts.json", json.dumps(report))


class InvalidDraftBaselineTests(unittest.TestCase):
    def test_previous_green_exact_readback_is_available_as_second_expected_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "baseline.zip"
            _archive(archive)
            previous = load_previous_exact_versions(archive, {LEAD_ID})
            source = {
                LEAD_ID: {
                    "lead_id": LEAD_ID,
                    "status": "review_draft",
                    "contact_basis_status": "review_required",
                    "email": "info@example.nl",
                    "subject": "Old subject",
                    "body": "Old body",
                }
            }
            versions = build_expected_versions(source, previous)[LEAD_ID]["expected_versions"]
            self.assertEqual([v["subject"] for v in versions], ["Old subject", "New subject"])

    def test_previous_recipient_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "baseline.zip"
            _archive(archive, to="other@example.nl")
            previous = load_previous_exact_versions(archive, {LEAD_ID})
            source = {
                LEAD_ID: {
                    "lead_id": LEAD_ID,
                    "status": "review_draft",
                    "contact_basis_status": "review_required",
                    "email": "info@example.nl",
                    "subject": "Old subject",
                    "body": "Old body",
                }
            }
            with self.assertRaisesRegex(ValueError, "recipient"):
                build_expected_versions(source, previous)

    def test_failed_previous_audit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "baseline.zip"
            _archive(archive, failures=["mismatch"])
            with self.assertRaisesRegex(ValueError, "not an exact no-send pass"):
                load_previous_exact_versions(archive, {LEAD_ID})

    def test_expected_versions_file_is_bound_to_lead_and_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baselines.json"
            path.write_text(json.dumps({
                "schema_version": SCHEMA_VERSION,
                "lead_ids": {LEAD_ID: {
                    "expected_versions": [{
                        "to": "info@example.nl",
                        "subject": "Subject",
                        "body": "Body",
                        "review_status": "contact-basis",
                    }]
                }},
            }))
            versions = load_expected_versions(path, LEAD_ID)
            self.assertEqual(versions[0]["subject"], "Subject")
            with self.assertRaisesRegex(ValueError, "missing"):
                load_expected_versions(path, "growth-11111111111111111111")


if __name__ == "__main__":
    unittest.main()
