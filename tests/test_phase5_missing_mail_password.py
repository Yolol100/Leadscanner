from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from myhost_draft import create_drafts


class Phase5MissingPasswordTest(unittest.TestCase):
    def test_ready_draft_fails_before_imap_without_password(self):
        row = {
            "lead_id": "growth-0123456789abcdefabcd",
            "company": "Voorbeeld BV",
            "website": "https://voorbeeld.nl",
            "email": "info@voorbeeld.nl",
            "subject": "Idee voor Voorbeeld BV",
            "body": "Concept voor handmatige beoordeling.",
            "status": "review_draft",
            "contact_basis_status": "review_required",
        }
        with patch.dict(os.environ, {"OUTREACH_MAIL_PASSWORD": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "OUTREACH_MAIL_PASSWORD is required"):
                create_drafts({"rows": [row]})


if __name__ == "__main__":
    unittest.main()
