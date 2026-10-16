"""Synthetic tests of the private, read-only 450-draft inventory gate."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import live_450_draft_inventory as audit


class LiveDraftInventoryTests(unittest.TestCase):
    def rows(self):
        result = []
        for number in range(1, 451):
            row = [""] * 16
            row[0] = str(number)
            row[1] = "draft-" + format(number, "032x")
            row[2] = "Example company"
            row[3] = "info@example.invalid"
            row[5] = "Example subject"
            row[6] = (
                "Goedendag,\n\n"
                "Een korte uitleg over de dienstverlening.\n\n"
                "Zal ik iets laten zien?\n\n"
                + audit.OPT_OUT
                + "\n\nGroet,\nAndrew"
            )
            row[8] = "https://example.invalid"
            row[13] = (
                "BRONBLOKKADE_NIET_VERSTUREN"
                if number <= 38 else "VOOR_MENSELIJKE_EINDCONTROLE"
            )
            result.append(row)
        return result

    def test_expected_classification_and_unique_ids(self):
        with patch.object(audit.review, "read", return_value=self.rows()):
            expected = audit.load_expected(object())
        self.assertEqual(len(expected), 450)
        self.assertEqual(sum(x["blocked"] for x in expected.values()), 38)

    def test_fail_closed_on_duplicate_id(self):
        data = self.rows()
        data[1][1] = data[0][1]
        with patch.object(audit.review, "read", return_value=data):
            with self.assertRaisesRegex(RuntimeError, "private_review_invalid"):
                audit.load_expected(object())

    def test_no_mailbox_mutations(self):
        source = (Path(__file__).resolve().parents[1]
                  / "scripts" / "live_450_draft_inventory.py").read_text()
        self.assertNotIn("client.append(", source)
        self.assertNotIn('client.uid("STORE"', source)
        self.assertNotIn('client.uid("EXPUNGE"', source)
        self.assertNotIn("sendmail(", source)


if __name__ == "__main__":
    unittest.main()
