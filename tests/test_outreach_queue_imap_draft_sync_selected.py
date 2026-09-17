import unittest

import outreach_queue_imap_draft_sync_selected as selected


class SelectedDraftSyncTests(unittest.TestCase):
    def setUp(self):
        self.previous_ids = selected._SELECTED_IDS

    def tearDown(self):
        selected._SELECTED_IDS = self.previous_ids

    def test_blocks_selected_recipient_owned_by_another_lead(self):
        selected._SELECTED_IDS = ("lead-a",)
        values = [
            ["lead_id", "website", "email", "subject", "body"],
            ["lead-a", "https://example.com/", "info@example.com", "A", "Body A"],
            ["lead-b", "https://example.com/", "INFO@example.com", "B", "Body B"],
        ]

        with self.assertRaisesRegex(RuntimeError, "also assigned to another OutreachQueue lead"):
            selected._selected_target_rows(values, "unused", 1)

    def test_allows_selected_recipient_when_other_leads_use_other_addresses(self):
        selected._SELECTED_IDS = ("lead-a",)
        values = [
            ["lead_id", "website", "email", "subject", "body"],
            ["lead-a", "https://example.com/", "info@example.com", "A", "Body A"],
            ["lead-b", "https://example.org/", "sales@example.org", "B", "Body B"],
        ]

        rows = selected._selected_target_rows(values, "unused", 1)
        self.assertEqual([row["lead_id"] for row in rows], ["lead-a"])


if __name__ == "__main__":
    unittest.main()
