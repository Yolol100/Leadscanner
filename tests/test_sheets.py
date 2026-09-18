import unittest

from sheets import rows_from_values, selected_rows


class SheetSelectionTests(unittest.TestCase):
    def test_rows_from_values(self):
        values = [
            ["lead_id", "company"],
            ["lead-1", "Een BV"],
            ["lead-2", "Twee BV"],
        ]
        rows = rows_from_values(values)
        self.assertEqual(rows[0]["lead_id"], "lead-1")
        self.assertEqual(rows[1]["company"], "Twee BV")

    def test_missing_selected_lead_blocks(self):
        rows = [{"lead_id": "lead-1", "company": "Een BV"}]
        with self.assertRaises(RuntimeError):
            selected_rows(rows, ["lead-2"])

    def test_duplicate_selected_lead_blocks(self):
        rows = [
            {"lead_id": "lead-1", "company": "Een BV"},
            {"lead_id": "lead-1", "company": "Dubbel BV"},
        ]
        with self.assertRaises(RuntimeError):
            selected_rows(rows, ["lead-1"])

    def test_duplicate_unselected_lead_does_not_block_selected_good_lead(self):
        rows = [
            {"lead_id": "lead-1", "company": "Een BV"},
            {"lead_id": "lead-x", "company": "X BV"},
            {"lead_id": "lead-x", "company": "X Dubbel BV"},
        ]
        selected = selected_rows(rows, ["lead-1"])
        self.assertEqual(selected[0]["company"], "Een BV")


if __name__ == "__main__":
    unittest.main()
