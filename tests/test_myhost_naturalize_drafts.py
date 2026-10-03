from __future__ import annotations

import unittest
from email.message import EmailMessage

from myhost_naturalize_drafts import rewrite_row_from_message


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
                "Op jullie site viel me op: “Fysiotherapie in Utrecht”.\n\n"
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
        self.assertEqual(row["subject"], "Idee voor Voorbeeld Fysio")
        self.assertIn("Wat me opviel op jullie website: Fysiotherapie in Utrecht.", row["body"])
        self.assertIn("€250–€500 per maand", row["body"])
        self.assertEqual(len([line for line in row["body"].splitlines() if line.startswith("• ")]), 6)
        self.assertFalse(row["_already_natural"])

    def test_en_draft_becomes_natural_without_changing_recipient_or_subject(self):
        row = rewrite_row_from_message(self.message(language="en"))
        self.assertEqual(row["email"], "info@example.com")
        self.assertEqual(row["subject"], "An idea for Example Gym")
        self.assertIn("What stood out to me on your website: Personal training in Utrecht.", row["body"])
        self.assertIn("€250–€500 per month", row["body"])
        self.assertEqual(len([line for line in row["body"].splitlines() if line.startswith("• ")]), 6)

    def test_naturalization_is_idempotent(self):
        first = rewrite_row_from_message(self.message())
        msg = self.message()
        msg.set_content(first["body"])
        second = rewrite_row_from_message(msg)
        self.assertEqual(first["body"], second["body"])
        self.assertTrue(second["_already_natural"])


if __name__ == "__main__":
    unittest.main()
