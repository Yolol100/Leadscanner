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

    def test_known_generations_are_private_and_identity_checked(self):
        base = self.rows()
        with patch.object(audit.review, "read", return_value=base):
            expected = audit.load_expected(object())
        original = []
        openings = []
        quality = []
        styles = []
        for row in base:
            key, company = row[1], row[2]
            v = [""] * 16
            v[0], v[2], v[5], v[6] = key, company, "Original", row[6]
            original.append(v)
            opening = [""] * 17
            opening[1], opening[2], opening[3], opening[7] = (
                key, company, "Opening", row[6])
            openings.append(opening)
            revised = [""] * 13
            revised[1], revised[2], revised[4], revised[7] = (
                key, company, "Revision", row[6])
            quality.append(revised)
            style = [""] * 13
            style[0], style[1], style[2], style[6], style[7] = (
                row[0], key, company, "Conversation", row[6])
            styles.append(style)

        def private_read(_session, _sid, value_range):
            if value_range.startswith("Review450!"):
                return original
            if value_range.startswith("OpeningenReview20261016!"):
                return openings
            if value_range.startswith("'Conceptkwaliteit 20261018'!"):
                return quality
            for batch in range(1, 6):
                if value_range.startswith(f"'Gespreksstijl Fase{batch} 20261016'!"):
                    start = (batch - 1) * 100
                    return styles[start:min(start + 100, 450)]
            raise AssertionError("Unexpected private source range")

        with patch.object(audit.review, "read", side_effect=private_read):
            variants = audit.load_alternate_versions(object(), expected)
            self.assertEqual(
                {label: len(rows) for label, rows in variants.items()},
                {key: 450 for key in variants})
            self.assertEqual(
                variants["openingen"][base[0][1]]["subject"], "Opening")
            self.assertEqual(
                variants["gespreksstijl"][base[449][1]]["subject"], "Conversation")

        original[0][2] = "Wrong company"
        with patch.object(audit.review, "read", side_effect=private_read):
            with self.assertRaisesRegex(
                    RuntimeError, "private_versions_identity_invalid"):
                audit.load_alternate_versions(object(), expected)

    def test_missing_private_generation_blocks_without_mailbox_access(self):
        with patch.object(audit.review, "read", return_value=self.rows()):
            expected = audit.load_expected(object())
        with patch.object(audit.review, "read", return_value=[]):
            with self.assertRaisesRegex(
                    RuntimeError, "private_versions_count_invalid"):
                audit.load_alternate_versions(object(), expected)

    def test_active_short_format_is_separate_from_exact_historical_copy(self):
        legacy = {
            "subject": "Korte vraag over afspraak",
            "body": ("Goedendag,\n\nEen korte uitleg over onze dienstverlening."
                     "\n\nZal ik een social voorbeeld sturen?\n\n"
                     + audit.OPT_OUT + "\n\nGroet,\nAndrew")
        }
        self.assertFalse(audit.matches_current_style(legacy))
        current = dict(legacy)
        current["body"] = "\n\n".join((
            "Goedendag,",
            "Ik zag dat klanten bij jullie telefonisch een afspraak kunnen maken.",
            "Zou het handig zijn als klanten online zelf een tijdstip kunnen kiezen?",
            audit.OPT_OUT,
            "Groet,\nAndrew",
        ))
        self.assertTrue(audit.matches_current_style(current))

    def test_no_mailbox_mutations(self):
        source = (Path(__file__).resolve().parents[1]
                  / "scripts" / "live_450_draft_inventory.py").read_text()
        self.assertNotIn("client.append(", source)
        self.assertNotIn('client.uid("STORE"', source)
        self.assertNotIn('client.uid("EXPUNGE"', source)
        self.assertNotIn("sendmail(", source)


if __name__ == "__main__":
    unittest.main()
