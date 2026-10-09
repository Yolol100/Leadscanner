"""Deterministic, no-network migration safety tests."""
import unittest
from email.message import EmailMessage
from unittest.mock import patch

from myhost_instantly_import import (
    TARGET_LIST_NAME, execute_migration, extract_lead_draft, lead_payload,
    registry_allows_draft, unique_drafts, verify_import,
)

LEAD = "growth-" + "a" * 20


def mail(*, to="hello@example.org", lead=LEAD, sender="info@andrewbaeten.nl"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = "Een korte vraag"
    if lead:
        msg["X-Webactueel-Lead-ID"] = lead
    msg.set_content("Een kort, concreet idee.")
    return msg


class FakeInstantly:
    def __init__(self):
        self.calls = []
        self.lead = None

    def _request(self, method, path, *, params=None, json=None, retry_safe=False):
        self.calls.append((method, path, json))
        if path == "/block-lists-entries":
            return {"items": []}
        if path == "/lead-lists" and method == "GET":
            return {"items": []}
        if path == "/lead-lists" and method == "POST":
            return {"id": "test-list-id", "name": TARGET_LIST_NAME}
        if path == "/lead-lists/test-list-id":
            return {"id": "test-list-id", "name": TARGET_LIST_NAME}
        if path == "/leads" and method == "POST":
            self.lead = {"id": "test-lead-id", "email": json["email"], "list_id": json["list_id"], "campaign": None, "payload": json["custom_variables"]}
            return {"id": "test-lead-id"}
        raise AssertionError("unexpected provider request " + method + " " + path)

    def list_leads(self, **kwargs):
        self.calls.append(("POST", "/leads/list", None))
        return {"items": []}

    def get_lead(self, lead_id):
        return self.lead


class ImportTests(unittest.TestCase):
    def test_tagged_only_and_exact_sender(self):
        self.assertIsNone(extract_lead_draft(mail(lead=""), sender="info@andrewbaeten.nl"))
        self.assertEqual(extract_lead_draft(mail(), sender="info@andrewbaeten.nl")["email"], "hello@example.org")
        with self.assertRaisesRegex(ValueError, "source_sender_mismatch"):
            extract_lead_draft(mail(sender="other@example.net"), sender="info@andrewbaeten.nl")

    def test_multi_recipient_or_attachment_rejected(self):
        with self.assertRaisesRegex(ValueError, "source_single_valid_recipient"):
            extract_lead_draft(mail(to="one@example.com, two@example.com"), sender="info@andrewbaeten.nl")
        m = mail()
        m.add_attachment(b"file", maintype="application", subtype="octet-stream", filename="notes.txt")
        with self.assertRaisesRegex(ValueError, "attachments"):
            extract_lead_draft(m, sender="info@andrewbaeten.nl")

    def test_duplicates_excluded_not_chosen_arbitrarily(self):
        row = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")
        self.assertEqual(unique_drafts([row, dict(row)])[0], [])
        self.assertEqual(unique_drafts([row, dict(row)])[1], 2)

    def test_registry_negative_status_excluded(self):
        row = {"lead_id": LEAD, "email": "hello@example.org"}
        registry = [{"identity":{"company":"","emails":{"hello@example.org"},"domains":set(),"lead_ids":set()},"status":"verzonden","row_number":2}]
        self.assertFalse(registry_allows_draft(row, registry))
        registry[0]["status"] = "concept"
        self.assertTrue(registry_allows_draft(row, registry))

    def test_list_only_copy_variables_and_contact_basis(self):
        row = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")
        payload = lead_payload(row, "list123")
        self.assertEqual(payload["list_id"], "list123")
        self.assertNotIn("campaign", payload)
        self.assertFalse(payload.get("automatic_send", False))
        self.assertEqual(payload["custom_variables"]["leadscanner_contact_basis"], "review_required")

    def test_audit_never_writes(self):
        row = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")
        api = FakeInstantly()
        with patch("myhost_instantly_import.read_source_drafts", return_value={
            "source_count":1,"untagged_count":0,"invalid_tagged_count":0,"drafts":[row],
        }), patch("myhost_instantly_import.fetch_live_registry", return_value=[]):
            result = execute_migration(api, mode="audit")
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["imported_count"], 0)
        self.assertFalse(any(method == "POST" and path != "/leads/list" for method, path, _ in api.calls))

    def test_import_isolated_list_exact_readback(self):
        row = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")
        api = FakeInstantly()
        with patch("myhost_instantly_import.read_source_drafts", return_value={
            "source_count":1,"untagged_count":0,"invalid_tagged_count":0,"drafts":[row],
        }), patch("myhost_instantly_import.fetch_live_registry", return_value=[]):
            result = execute_migration(api, mode="import")
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["list_id"], "test-list-id")
        self.assertFalse(result["automatic_send"])
        self.assertFalse(result["campaign_mutation"])
        self.assertFalse(result["imap_mutation"])
        self.assertFalse(any("/campaigns" in path or "/emails" in path for _,path,_ in api.calls))

    def test_import_respects_batch_limit(self):
        row1 = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")
        row2 = extract_lead_draft(mail(to="two@example.org", lead="growth-" + "b" * 20), sender="info@andrewbaeten.nl")
        api = FakeInstantly()
        with patch("myhost_instantly_import.read_source_drafts", return_value={
            "source_count":2,"untagged_count":0,"invalid_tagged_count":0,"drafts":[row1,row2],
        }), patch("myhost_instantly_import.fetch_live_registry", return_value=[]):
            result = execute_migration(api, mode="import", max_imports=1)
        self.assertEqual(result["eligible_count"], 2)
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["deferred_count"], 1)
        self.assertEqual(sum(1 for method,path,_ in api.calls if method == "POST" and path == "/leads"), 1)

    def test_workspace_snapshot_skips_existing_before_import(self):
        row = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")

        class Existing(FakeInstantly):
            def list_leads(self, **kwargs):
                self.calls.append(("POST", "/leads/list", None))
                if not kwargs.get("contacts"):
                    return {"items":[{"email":row["email"]}],"next_starting_after":None}
                return {"items":[]}

        api = Existing()
        with patch("myhost_instantly_import.read_source_drafts", return_value={
            "source_count":1,"untagged_count":0,"invalid_tagged_count":0,"drafts":[row],
        }), patch("myhost_instantly_import.fetch_live_registry", return_value=[]):
            result = execute_migration(api, mode="import", max_imports=1)
        self.assertEqual(result["already_in_workspace_count"], 1)
        self.assertEqual(result["eligible_count"], 0)
        self.assertEqual(result["imported_count"], 0)
        self.assertFalse(any(method == "POST" and path == "/leads" for method,path,_ in api.calls))

    def test_import_limit_bounds_fail_closed(self):
        api = FakeInstantly()
        for count in (0, 251, True, "25"):
            with self.assertRaisesRegex(ValueError, "max_imports_out_of_bounds"):
                execute_migration(api, mode="import", max_imports=count)

    def test_privacy_safe_stage_label_on_upstream_failure(self):
        row = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")
        api = FakeInstantly()
        with patch("myhost_instantly_import.read_source_drafts", return_value={
            "source_count":1,"untagged_count":0,"invalid_tagged_count":0,"drafts":[row],
        }), patch("myhost_instantly_import.fetch_live_registry", return_value=[]), patch(
            "myhost_instantly_import.fetch_all_leads", side_effect=RuntimeError("sensitive upstream detail")
        ):
            with self.assertRaisesRegex(RuntimeError, "^migration_step_workspace_snapshot_RuntimeError$"):
                execute_migration(api, mode="audit")

    def test_readback_rejects_wrong_campaign(self):
        row = extract_lead_draft(mail(), sender="info@andrewbaeten.nl")
        payload = lead_payload(row, "list123")
        api = FakeInstantly()
        api.lead = {"id":"lead123","email":row["email"],"list_id":"list123","campaign":"active","payload":payload["custom_variables"]}
        with self.assertRaisesRegex(RuntimeError, "lead_not_in_isolated_list"):
            verify_import(api, payload, {"id":"lead123"})


if __name__ == "__main__":
    unittest.main()
