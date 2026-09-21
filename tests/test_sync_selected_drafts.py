import os
import tempfile
import unittest
from unittest.mock import patch

from sync_selected_drafts import run


class SyncSelectedDraftsTests(unittest.TestCase):
    def test_missing_private_postal_config_blocks_before_imap(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("lead-1\n")
            lead_file = handle.name

        try:
            with (
                patch.dict(os.environ, {"OUTREACH_SPREADSHEET_ID": "sheet-test"}, clear=False),
                patch("sync_selected_drafts.build_service", return_value=object()),
                patch("sync_selected_drafts.get_values", return_value=[["lead_id"], ["lead-1"]]),
                patch("sync_selected_drafts.rows_from_values", return_value=[{"lead_id": "lead-1"}]),
                patch("sync_selected_drafts.selected_rows", return_value=[{"lead_id": "lead-1"}]),
                patch("sync_selected_drafts.validate_row", return_value={"lead_id": "lead-1"}),
                patch(
                    "sync_selected_drafts.load_private_postal_address",
                    side_effect=RuntimeError("OUTREACH_POSTAL_ADDRESS is missing from private config"),
                ),
                patch("sync_selected_drafts.connect_imap") as connect_imap,
            ):
                with self.assertRaisesRegex(RuntimeError, "OUTREACH_POSTAL_ADDRESS"):
                    run(lead_file, 1)
                connect_imap.assert_not_called()
        finally:
            os.unlink(lead_file)


if __name__ == "__main__":
    unittest.main()
