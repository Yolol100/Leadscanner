import unittest

from instantly_webhook import apply_registry_event, normalize_event, plan_registry_event_update
from update_dedupe_registry import HEADERS


def row(status="sent"):
    return [
        "Acme", "https://acme.nl/", "acme.nl", "info@acme.nl",
        status, "drafted", "growth-aaaaaaaaaaaaaaaaaaaa", "",
        "cold_pipeline_review_draft", "TRUE",
    ]


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class FakeSheetSession:
    def __init__(self, live_row):
        self.live_row = list(live_row)
        self.put_calls = []

    def get(self, url, timeout=20):
        return FakeResponse(payload={"values": [list(self.live_row)]})

    def put(self, url, json, timeout=20):
        self.put_calls.append((url, json))
        self.live_row = list(json["values"][0])
        return FakeResponse(payload={"updatedRows": 1})


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
            {"event_type": "lead_unsubscribed", "lead_email": "info@acme.nl", "timestamp": "2026-10-07T10:00:00Z"},
            [HEADERS, row()],
        )
        second = plan_registry_event_update(
            {"event_type": "campaign_completed", "lead_email": "info@acme.nl", "timestamp": "2026-10-07T11:00:00Z"},
            [HEADERS, first["after"]],
        )
        self.assertEqual(second["after"][4], "unsubscribed")

    def test_closed_status_is_terminal_against_later_campaign_complete(self):
        first = plan_registry_event_update(
            {"event_type": "lead_closed", "lead_email": "info@acme.nl", "timestamp": "2026-10-07T10:00:00Z"},
            [HEADERS, row()],
        )
        second = plan_registry_event_update(
            {"event_type": "campaign_completed", "lead_email": "info@acme.nl", "timestamp": "2026-10-07T11:00:00Z"},
            [HEADERS, first["after"]],
        )
        self.assertEqual(second["after"][4], "closed")

    def test_interest_status_supported(self):
        event = normalize_event({
            "event_type": "lead_interested",
            "lead_email": "info@acme.nl",
            "timestamp": "2026-10-07T12:00:00Z",
        })
        self.assertEqual(event["kind"], "interested")

    def test_meeting_booked_event_is_supported(self):
        event = normalize_event({
            "event_type": "lead_meeting_booked",
            "lead_email": "info@acme.nl",
            "timestamp": "2026-10-07T12:00:00Z",
        })
        self.assertEqual(event["kind"], "meeting_booked")

    def test_poll_source_marker_is_recorded_instead_of_webhook_marker(self):
        plan = plan_registry_event_update(
            {
                "event_type": "reply_received",
                "lead_email": "info@acme.nl",
                "timestamp": "2026-10-07T13:00:00Z",
            },
            [HEADERS, row()],
            source_marker="instantly:poll",
        )
        self.assertIn("instantly:poll", plan["after"][8])
        self.assertNotIn("instantly:webhook", plan["after"][8])

    def test_polled_terminal_events_are_supported(self):
        lost = normalize_event({
            "event_type": "lead_lost",
            "lead_email": "info@acme.nl",
            "timestamp": "2026-10-07T12:00:00Z",
        })
        skipped = normalize_event({
            "event_type": "lead_skipped",
            "lead_email": "info@acme.nl",
            "timestamp": "2026-10-07T12:00:00Z",
        })
        self.assertEqual(lost["kind"], "lost")
        self.assertEqual(skipped["kind"], "skipped")

    def test_older_event_cannot_roll_back_newer_registry_state(self):
        current = row("interested")
        current[7] = "2026-10-07T15:00:00Z"
        plan = plan_registry_event_update(
            {
                "event_type": "reply_received",
                "lead_email": "info@acme.nl",
                "timestamp": "2026-10-07T14:00:00Z",
            },
            [HEADERS, current],
            source_marker="instantly:poll",
        )
        self.assertTrue(plan["safety"]["stale_event_ignored"])
        self.assertEqual(plan["after"], plan["before"])

    def test_apply_rechecks_fresh_row_before_write(self):
        stale_snapshot = row("sent")
        stale_snapshot[7] = "2026-10-07T12:00:00Z"
        fresh_row = row("unsubscribed")
        fresh_row[5] = "drafted;instantly:lead_unsubscribed"
        fresh_row[7] = "2026-10-07T15:00:00Z"
        session = FakeSheetSession(fresh_row)

        plan = apply_registry_event(
            session,
            "sheet-1",
            "DedupeRegistry",
            {
                "event_type": "reply_received",
                "lead_email": "info@acme.nl",
                "timestamp": "2026-10-07T14:00:00Z",
            },
            [HEADERS, stale_snapshot],
            source_marker="instantly:poll",
        )

        self.assertTrue(plan["safety"]["stale_event_ignored"])
        self.assertEqual(plan["before"], fresh_row)
        self.assertEqual(session.put_calls, [])

    def test_malformed_timestamp_fails_closed_before_registry_change(self):
        with self.assertRaisesRegex(ValueError, "webhook_timestamp_invalid"):
            normalize_event({
                "event_type": "reply_received",
                "lead_email": "info@acme.nl",
                "timestamp": "not-a-timestamp",
            })

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
