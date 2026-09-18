import os
import re
import unittest
from unittest.mock import patch

from outreach_compliance_preflight import COMPLIANCE_NOT_PROVEN, COMPLIANCE_PASSED, GATE_2
from outreach_copy_v17_3 import build_curiosity_first_copy
from outreach_queue_imap_draft import (
    inject_private_postal_for_draft,
    resolve_queue_row,
    suppression_sets,
    validate_queue_row,
)


def good_row(**overrides):
    copy = build_curiosity_first_copy(
        company="Example",
        language="en",
        subject="Quote requests Example",
        observation='I noticed your site routes visitors directly to "Request a quote" for roofing work',
        friction="That can create avoidable back-and-forth before the basic request details are complete",
        example_label="mini-flow",
    )
    row = {
        "lead_id": "prospect-abc",
        "email": "partnerships@example.com",
        "subject": copy.subject,
        "body": copy.body,
        "status": "manual_review",
        "country": "NL",
        "contact_verified": "true",
        "contact_source": "https://example.com/partnerships",
        "compliance_status": COMPLIANCE_PASSED,
        "compliance_basis": "explicit_designation",
        "compliance_gate_used": GATE_2,
        "compliance_evidence": 'Official page states "business proposals: partnerships@example.com"',
        "compliance_source": "https://example.com/partnerships",
        "compliance_checked_at": "2026-09-18T00:00:00Z",
        "compliance_purpose_match": "true",
        "outreach_allowed": "true",
        "stage": "1",
        "sender_email": "info@andrewbaeten.nl",
    }
    row.update(overrides)
    return row


class QueueImapDraftTests(unittest.TestCase):
    def test_resolve_requires_one_exact_lead(self):
        values = [["lead_id", "email", "status"], ["lead-1", "one@example.com", "manual_review"]]
        row = resolve_queue_row(values, "lead-1")
        self.assertEqual(row["email"], "one@example.com")
        with self.assertRaises(RuntimeError):
            resolve_queue_row(values, "missing")
        with self.assertRaises(ValueError):
            resolve_queue_row(values, "bad lead id")

    def test_suppression_sets_are_normalized(self):
        values = [["email", "domain", "reason"], ["Stop@Example.com", "Blocked.test", "optout"]]
        emails, domains = suppression_sets(values)
        self.assertEqual(emails, {"stop@example.com"})
        self.assertEqual(domains, {"blocked.test"})

    def test_placeholder_draft_injects_private_address_at_runtime(self):
        row = {"country": "US"}
        body = "Best regards,\nAndrew Baeten\n{{OUTREACH_POSTAL_ADDRESS}}\nandrewbaeten.nl"
        with patch.dict(os.environ, {"OUTREACH_POSTAL_ADDRESS": "123 Example Street\nExample City\nExample Country"}, clear=False):
            rendered = inject_private_postal_for_draft(row, body)
        self.assertNotIn("{{OUTREACH_POSTAL_ADDRESS}}", rendered)
        self.assertIn("Andrew Baeten\n123 Example Street", rendered)
        self.assertTrue(rendered.endswith("Example Country\nandrewbaeten.nl"))

    def test_nl_draft_appends_private_address_when_copy_has_no_placeholder(self):
        body = "Met vriendelijke groet,\nAndrew Baeten\nandrewbaeten.nl"
        with patch.dict(os.environ, {"OUTREACH_POSTAL_ADDRESS": "Zakelijk postadres 1\n3011 AA Rotterdam"}, clear=False):
            rendered = inject_private_postal_for_draft({"country": "NL"}, body)
        self.assertTrue(rendered.endswith("Zakelijk postadres 1\n3011 AA Rotterdam"))
        self.assertEqual(rendered.count("Zakelijk postadres 1"), 1)

    def test_commercial_draft_fails_closed_without_private_address(self):
        old = os.environ.pop("OUTREACH_POSTAL_ADDRESS", None)
        try:
            with self.assertRaises(RuntimeError):
                inject_private_postal_for_draft({"country": "NL"}, "Met vriendelijke groet")
        finally:
            if old is not None:
                os.environ["OUTREACH_POSTAL_ADDRESS"] = old

    def test_valid_compliance_passed_row_can_be_drafted(self):
        self.assertEqual(validate_queue_row(good_row(), sender_email="info@andrewbaeten.nl"), [])

    def test_contact_verification_is_independent_and_required(self):
        errors = validate_queue_row(good_row(contact_verified="false"), sender_email="info@andrewbaeten.nl")
        self.assertTrue(any("contact_verified is not true" in error for error in errors))

    def test_compliance_not_proven_blocks_draft(self):
        row = good_row(
            email="info@example.com",
            compliance_status=COMPLIANCE_NOT_PROVEN,
            compliance_basis="",
            compliance_gate_used="",
            compliance_evidence="",
            compliance_source="",
            compliance_checked_at="",
            compliance_purpose_match="false",
            outreach_allowed="false",
        )
        errors = validate_queue_row(row, sender_email="info@andrewbaeten.nl")
        self.assertIn("compliance_status is not COMPLIANCE_PASSED", errors)

    def test_solution_spoiler_is_blocked_before_draft(self):
        row = good_row()
        row["body"], count = re.subn(
            r"I can make [^\n]+",
            "For you, that could mean: customers answer five questions first and then the team receives a complete request.",
            row["body"],
            count=1,
        )
        self.assertEqual(count, 1, "generated first-touch must contain the example paragraph")
        errors = validate_queue_row(row, sender_email="info@andrewbaeten.nl")
        self.assertTrue(any(error.startswith("copy contract:") for error in errors))
        self.assertTrue(any("full solution" in error for error in errors))

    def test_unproven_artifact_claim_is_blocked_before_draft(self):
        copy = build_curiosity_first_copy(
            company="Example",
            language="en",
            subject="Quote requests Example",
            observation='I noticed your site routes visitors directly to "Request a quote" for roofing work',
            friction="That can create avoidable back-and-forth before the basic request details are complete",
            example_label="mini-flow",
            artifact_ready=True,
        )
        row = good_row(subject=copy.subject, body=copy.body)
        errors = validate_queue_row(row, sender_email="info@andrewbaeten.nl")
        self.assertTrue(any("artifact readback proof" in error for error in errors))

    def test_proven_artifact_claim_is_allowed_before_draft(self):
        copy = build_curiosity_first_copy(
            company="Example",
            language="en",
            subject="Quote requests Example",
            observation='I noticed your site routes visitors directly to "Request a quote" for roofing work',
            friction="That can create avoidable back-and-forth before the basic request details are complete",
            example_label="mini-flow",
            artifact_ready=True,
        )
        row = good_row(
            subject=copy.subject,
            body=copy.body,
            artifact_exists="true",
            artifact_readback_verified="true",
        )
        self.assertEqual(validate_queue_row(row, sender_email="info@andrewbaeten.nl"), [])

    def test_draft_blocks_suppressed_or_already_sent_rows(self):
        row = good_row(sent_at="2026-09-09T08:00:00Z")
        errors = validate_queue_row(row, sender_email="info@andrewbaeten.nl", suppressed_domains={"example.com"})
        self.assertIn("queue row already has send/reply/bounce evidence", errors)
        self.assertIn("recipient is suppressed", errors)

    def test_draft_requires_sender_match(self):
        row = good_row(status="prepared", sender_email="other@example.com")
        errors = validate_queue_row(row, sender_email="info@andrewbaeten.nl")
        self.assertIn("queue sender does not match configured mailbox sender", errors)


if __name__ == "__main__":
    unittest.main()
