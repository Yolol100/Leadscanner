from __future__ import annotations

import unittest
from email.message import EmailMessage
from unittest.mock import patch
import sys

from myhost_naturalize_drafts import main, run_inventory_slice, rewrite_row_from_message


class MyHostNaturalizeDraftTests(unittest.TestCase):
    def message(self, *, language: str = "nl") -> EmailMessage:
        msg = EmailMessage()
        msg["To"] = "info@example.com"
        msg["X-Webactueel-Lead-ID"] = "growth-1234567890abcdef1234"
        msg["X-Webactueel-Review-Required"] = "contact-basis"
        if language == "en":
            msg["Subject"] = "An idea for Example Gym"
            msg.set_content(
                "Hello,\n\n"
                "I noticed this on your website: “Personal training in Utrecht”.\n\n"
                "With my Growth Subscription I help with:\n\n"
                "• Website/webshop — improve or build new where needed\n"
                "• Search visibility — improve findability\n"
                "• Social content — relevant content\n"
                "• Automation — partially automate suitable processes where feasible\n"
                "• Hosting — manage or take over where appropriate\n"
                "• Me as your fixed point of contact\n\n"
                "€250–€500 per month, depending on what you need.\n\n"
                "Would you like me to make a no-obligation example design for Example Gym, "
                "so you can first see whether the direction is relevant?\n\n"
                "Not interested? Just let me know.\n\n"
                "Regards,\nAndrew"
            )
        else:
            msg["Subject"] = "Idee voor Voorbeeld Fysio"
            msg.set_content(
                "Goedendag,\n\n"
                "Op jullie site viel me op: “Wij bieden fysiotherapie in Utrecht.”.\n\n"
                "Met mijn Groeiabonnement help ik met:\n\n"
                "• Website/webshop — verbeteren of nieuw maken waar nodig\n"
                "• Zoekbaarheid — beter vindbaar worden\n"
                "• Social content — passende content\n"
                "• Automatisering — geschikte processen deels automatiseren waar haalbaar\n"
                "• Hosting — beheren of overnemen waar passend\n"
                "• Ik als vast contactpersoon\n\n"
                "€250–€500 per maand, afhankelijk van wat jullie nodig hebben.\n\n"
                "Zal ik vrijblijvend een voorbeeld design maken voor Voorbeeld Fysio? "
                "Dan kunnen jullie eerst bekijken of de richting interessant is.\n\n"
                "Geen interesse? Laat het gerust weten.\n\n"
                "Groet,\nAndrew"
            )
        return msg

    def test_nl_draft_becomes_natural_without_changing_recipient_or_subject(self):
        row = rewrite_row_from_message(self.message())
        self.assertEqual(row["email"], "info@example.com")
        self.assertEqual(row["subject"], "idee voor voorbeeld fysio")
        self.assertTrue(row["body"].startswith("Hallo,\n\n"))
        self.assertIn("Jullie zijn actief in fysiotherapie en revalidatie.", row["body"])
        self.assertIn(
            "Wat me opviel: op jullie website staat dat jullie fysiotherapie in Utrecht aanbieden.",
            row["body"],
        )
        self.assertNotIn("€", row["body"])
        self.assertIn("Geen interesse? Laat het gerust weten.", row["body"])
        self.assertEqual(len([line for line in row["body"].splitlines() if line.startswith("• ")]), 0)
        self.assertFalse(row["_already_natural"])

    def test_nl_stale_subject_is_canonicalized(self):
        msg = self.message()
        msg.replace_header("Subject", "Oud Groeiabonnement onderwerp")
        row = rewrite_row_from_message(msg)
        self.assertEqual(row["subject"], "Idee voor Voorbeeld Fysio")
        self.assertFalse(row["_already_natural"])

    def test_en_draft_becomes_natural_without_changing_recipient_or_subject(self):
        row = rewrite_row_from_message(self.message(language="en"))
        self.assertEqual(row["email"], "info@example.com")
        self.assertEqual(row["subject"], "an idea for example gym")
        self.assertIn("What stood out: Personal training in Utrecht.", row["body"])
        self.assertNotIn("€", row["body"])
        self.assertEqual(len([line for line in row["body"].splitlines() if line.startswith("• ")]), 0)


    @patch("myhost_naturalize_drafts.read_review_growth_rows_slice_all")
    def test_inventory_slice_is_read_only_and_bounded(self, read_slice):
        read_slice.return_value = (
            "Drafts",
            1350,
            [
                {"_already_natural": True},
                {"_already_natural": False},
            ],
        )
        result = run_inventory_slice(100, 2)
        self.assertEqual(result["mode"], "inventory_slice")
        self.assertEqual(result["review_growth_total"], 1350)
        self.assertEqual(result["selected_count"], 2)
        self.assertEqual(result["naturalized_count"], 1)
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["offset"], 100)
        self.assertEqual(result["limit"], 2)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["smtp_send"], "not_available")
        read_slice.assert_called_once_with(100, 2)

    @patch("myhost_naturalize_drafts.run_inventory_slice")
    def test_cli_accepts_inventory_slice_mode(self, run_slice):
        run_slice.return_value = {
            "mode": "inventory_slice",
            "draft_folder": "Drafts",
            "review_growth_total": 1350,
            "naturalized_count": 100,
            "pending_count": 0,
            "selected_count": 100,
            "replaced_count": 0,
            "existing_count": 100,
            "created_count": 0,
            "smtp_send": "not_available",
            "read_only": True,
        }
        with patch.object(sys, "argv", ["myhost_naturalize_drafts.py", "--mode", "inventory_slice", "--offset", "0", "--limit", "100"]):
            self.assertEqual(main(), 0)
        run_slice.assert_called_once_with(0, 100)

    def test_verified_fact_opening_is_idempotent(self):
        first = rewrite_row_from_message(self.message())
        msg = self.message()
        msg.replace_header("Subject", first["subject"])
        msg.set_content(first["body"])
        second = rewrite_row_from_message(msg)
        self.assertEqual(first["body"], second["body"])
        self.assertEqual(
            second["body"].count(
                "Wat me opviel: op jullie website staat dat jullie fysiotherapie in Utrecht aanbieden."
            ),
            1,
        )

    def test_naturalization_is_idempotent(self):
        first = rewrite_row_from_message(self.message())
        msg = self.message()
        msg.set_content(first["body"])
        second = rewrite_row_from_message(msg)
        self.assertEqual(first["body"], second["body"])
        self.assertTrue(second["_already_natural"])


if __name__ == "__main__":
    unittest.main()

