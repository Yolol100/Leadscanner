import unittest

from instantly_sync import event_from_lead, fetch_all_leads, select_events


class FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def list_leads(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0)


class InstantlySyncTests(unittest.TestCase):
    def test_official_lead_statuses_map_to_suppression_events(self):
        bounced = event_from_lead(
            {
                "id": "l1",
                "email": "a@example.com",
                "status": -1,
                "lt_interest_status": 999,
                "timestamp_updated": "2026-10-07T10:00:00Z",
            }
        )
        unsubscribed = event_from_lead(
            {
                "id": "l2",
                "email": "b@example.com",
                "status": -2,
                "lt_interest_status": 999,
                "timestamp_updated": "2026-10-07T11:00:00Z",
            }
        )
        completed = event_from_lead(
            {
                "id": "l3",
                "email": "c@example.com",
                "status": 3,
                "lt_interest_status": 999,
                "timestamp_updated": "2026-10-07T12:00:00Z",
            }
        )
        self.assertEqual(bounced["event_type"], "email_bounced")
        self.assertEqual(unsubscribed["event_type"], "lead_unsubscribed")
        self.assertEqual(completed["event_type"], "campaign_completed_for_lead_without_reply")

    def test_interest_statuses_map_to_current_instantly_meaning(self):
        expected = {
            4: "lead_closed",
            3: "lead_meeting_completed",
            2: "lead_meeting_booked",
            1: "lead_interested",
            0: "lead_out_of_office",
            -1: "lead_not_interested",
            -2: "lead_wrong_person",
            -4: "lead_no_show",
        }
        for value, event_type in expected.items():
            with self.subTest(value=value):
                event = event_from_lead(
                    {
                        "id": f"lead-{value}",
                        "email": f"lead{value}@example.com",
                        "status": 1,
                        "lt_interest_status": value,
                        "timestamp_last_interest_change": "2026-10-07T13:00:00Z",
                    }
                )
                self.assertEqual(event["event_type"], event_type)

    def test_unsubscribe_wins_when_same_email_has_multiple_leads(self):
        events = select_events(
            [
                {
                    "id": "old",
                    "email": "same@example.com",
                    "status": 1,
                    "lt_interest_status": 1,
                    "timestamp_last_interest_change": "2026-10-07T12:00:00Z",
                },
                {
                    "id": "new",
                    "email": "same@example.com",
                    "status": -2,
                    "lt_interest_status": 999,
                    "timestamp_updated": "2026-10-07T13:00:00Z",
                },
            ]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "lead_unsubscribed")

    def test_reply_maps_only_when_no_more_specific_interest_state_exists(self):
        event = event_from_lead(
            {
                "id": "l1",
                "email": "reply@example.com",
                "status": 1,
                "lt_interest_status": 999,
                "email_reply_count": 1,
                "timestamp_last_reply": "2026-10-07T14:00:00Z",
            }
        )
        self.assertEqual(event["event_type"], "reply_received")

    def test_pagination_uses_next_starting_after(self):
        client = FakeClient(
            [
                {
                    "items": [{"id": "l1"}],
                    "next_starting_after": "cursor-1",
                },
                {
                    "items": [{"id": "l2"}],
                    "next_starting_after": None,
                },
            ]
        )
        rows = fetch_all_leads(client, max_leads=200)
        self.assertEqual([row["id"] for row in rows], ["l1", "l2"])
        self.assertIsNone(client.calls[0]["starting_after"])
        self.assertEqual(client.calls[1]["starting_after"], "cursor-1")


if __name__ == "__main__":
    unittest.main()
