from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from instantly_bridge import (
    InstantlyError,
    SAFE_CAMPAIGN_WRITE_STATUSES,
    _load_selected_ids,
    row_to_instantly_lead,
    sync_rows,
)


class FakeClient:
    def __init__(self, *, campaign_status=0, existing=()):
        self.campaign_status = campaign_status
        self.existing = set(existing)
        self.added = []

    def get_campaign(self, campaign_id):
        return {"id": campaign_id, "status": self.campaign_status}

    def list_leads_for_contacts(self, *, contacts, campaign_id="", list_id=""):
        return [{"email": email} for email in contacts if email in self.existing]

    def add_leads(self, leads, *, campaign_id="", list_id=""):
        self.added.extend(leads)
        self.existing.update(lead["email"] for lead in leads)
        return {"status": "ok"}


class InstantlyBridgeTests(unittest.TestCase):
    def test_selected_ids_are_exact_and_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.txt"
            path.write_text("lead-1\nlead-2\n", encoding="utf-8")
            self.assertEqual(_load_selected_ids(str(path), 2), ("lead-1", "lead-2"))
            with self.assertRaises(ValueError):
                _load_selected_ids(str(path), 1)

    def test_row_payload_only_contains_allowlisted_fields(self):
        payload = row_to_instantly_lead(
            {
                "lead_id": "lead-1",
                "email": "TEST@Example.com ",
                "company_name": "Example BV",
                "website": "https://example.com",
                "offer_type": "quote_intake",
                "body": "private draft body",
                "subject": "private subject",
            }
        )
        self.assertEqual(payload["email"], "test@example.com")
        self.assertEqual(payload["company_name"], "Example BV")
        self.assertEqual(payload["custom_variables"]["webactueel_lead_id"], "lead-1")
        self.assertNotIn("body", payload)
        self.assertNotIn("subject", payload)

    def test_dry_run_does_not_write(self):
        rows = [{"lead_id": "lead-1", "email": "a@example.com"}]
        client = FakeClient(existing=())
        result = sync_rows(client, rows, list_id="list-12345678", apply=False)
        self.assertEqual(result.submitted, 0)
        self.assertEqual(client.added, [])

    def test_apply_reads_back_every_selected_lead(self):
        rows = [
            {"lead_id": "lead-1", "email": "a@example.com"},
            {"lead_id": "lead-2", "email": "b@example.com"},
        ]
        client = FakeClient(existing={"a@example.com"})
        result = sync_rows(client, rows, list_id="list-12345678", apply=True)
        self.assertEqual(result.target, 2)
        self.assertEqual(result.existing, 1)
        self.assertEqual(result.submitted, 1)
        self.assertEqual(result.final_readback, 2)

    def test_active_campaign_is_fail_closed(self):
        self.assertNotIn(1, SAFE_CAMPAIGN_WRITE_STATUSES)
        rows = [{"lead_id": "lead-1", "email": "a@example.com"}]
        client = FakeClient(campaign_status=1)
        with self.assertRaises(InstantlyError):
            sync_rows(client, rows, campaign_id="campaign-12345678", apply=True)
        self.assertEqual(client.added, [])


if __name__ == "__main__":
    unittest.main()
