import unittest

from instantly_webhook import normalize_event, plan_registry_event_update
from update_dedupe_registry import HEADERS


def row(status="sent"):
    return [
        "Acme", "https://acme.nl/", "acme.nl", "info@acme.nl",
        status, "drafted", "growth-aaaaaaaaaaaaaaaaaaaa", "",
        "cold_pipeline_review_draft", "TRUE",
    ]


class InstantlyWebhookTests(unittest.TestCase):
    def test_reply_updates_existing_row_without_creating(self):
        plan = plan_registry_event_update(
            {
                "event_type": "reply_received",
                "lead_email": "info@acme.nl",
                "timestamp": "2026-10-07T13:00:00Z",
                "campaign_id": "c1",
            },
            [HEADERS, row()],
        )
        self.assertEqual(plan["after"][4], "replied")
        self.assertIn("instantly:reply_received", plan["after"][5])
        self.assertIn("instantly:webhook", plan["after"][8])
        self.assertEqual(plan["after"][9], "TRUE")
        self.assertFalse(plan["safety"]["creates_new_registry_row"])

    def test_unsubscribe_is_terminal_against_later_campaign_complete(self):
        first = plan_registry_event_update(
            {"event_type": "lead_unsubscribed", "lead_email": "info@acme.nl", "timestamp": "t1"},
            [HEADERS, row()],
        )
        second = plan_registry_event_update(
            {"event_type": "campaign_completed", "lead_email": "info@acme.nl", "timestamp": "t2"},
            [HEADERS, first["after"]],
        )
        self.assertEqual(second["after"][4], "unsubscribed")

    def test_interest_status_supported(self):
        event = normalize_event({
            "event_type": "lead_interested",
            "lead_email": "info@acme.nl",
            "timestamp": "t",
        })
        self.assertEqual(event["kind"], "interested")

    def test_unknown_event_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unsupported_instantly_event"):
            normalize_event({"event_type": "email_opened", "lead_email": "info@acme.nl"})

    def test_unmatched_or_ambiguous_identity_fails_closed(self):
        payload = {"event_type": "email_bounced", "lead_email": "info@acme.nl"}
        with self.assertRaisesRegex(ValueError, "identity_not_found"):
            plan_registry_event_update(payload, [HEADERS])
        with self.assertRaisesRegex(ValueError, "identity_ambiguous"):
            plan_registry_event_update(payload, [HEADERS, row(), row()])


if __name__ == "__main__":
    unittest.main()
