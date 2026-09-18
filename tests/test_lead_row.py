import unittest

from lead_row import validate_row


class LeadRowTests(unittest.TestCase):
    def base(self):
        return {
            "lead_id": "lead-1",
            "company": "Voorbeeld BV",
            "website": "https://example.nl/",
            "email": "info@example.nl",
            "subject": "Kleine website kans",
            "body": (
                "Beste team, op jullie website zag ik dat de contactroute voor nieuwe aanvragen vrij algemeen is. "
                "Ik kan één kort voorbeeld maken van een duidelijkere eerste stap die beter past bij jullie website. "
                "Zal ik het voorbeeld sturen? Geen interesse? Een kort nee is genoeg. "
                "Met vriendelijke groet, Andrew Baeten, andrewbaeten.nl"
            ),
        }

    def test_valid_row(self):
        self.assertEqual(validate_row(self.base())["lead_id"], "lead-1")

    def test_placeholder_blocks(self):
        row = self.base()
        row["body"] += " {{NAME}}"
        with self.assertRaises(ValueError):
            validate_row(row)

    def test_missing_optout_blocks(self):
        row = self.base()
        row["body"] = row["body"].replace("Geen interesse? Een kort nee is genoeg. ", "")
        with self.assertRaises(ValueError):
            validate_row(row)


if __name__ == "__main__":
    unittest.main()
