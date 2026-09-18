import os
import unittest
from unittest.mock import patch

from myhost_draft import build_message


class DraftTests(unittest.TestCase):
    def test_build_message_is_draft_content_only(self):
        row = {
            "lead_id": "lead-1",
            "email": "info@example.nl",
            "subject": "Kleine website kans",
            "body": "Beste team. Geen interesse? Een kort nee is genoeg. Andrew Baeten andrewbaeten.nl",
        }
        with patch.dict(os.environ, {"OUTREACH_SENDER_NAME":"Andrew Baeten","OUTREACH_SENDER_EMAIL":"info@andrewbaeten.nl"}, clear=False):
            msg = build_message(row, "Zakelijk postadres 1, Rotterdam")
        self.assertEqual(msg["To"], "info@example.nl")
        self.assertEqual(msg["X-Webactueel-Lead-ID"], "lead-1")
        self.assertIn("Zakelijk postadres 1, Rotterdam", msg.get_content())


if __name__ == "__main__":
    unittest.main()
