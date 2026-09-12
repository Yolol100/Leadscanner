from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_WORKFLOW = ROOT / ".github/workflows/migrate-legacy-myhost-draft-command.yml"
MIGRATION_SCRIPT = ROOT / "scripts/outreach_legacy_draft_migrate.py"
SELECTED_SYNC_WORKFLOW = ROOT / ".github/workflows/sync-selected-myhost-drafts-command.yml"


class LegacyDraftMigrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.migration_workflow = MIGRATION_WORKFLOW.read_text(encoding="utf-8")
        self.migration_script = MIGRATION_SCRIPT.read_text(encoding="utf-8")
        self.selected_sync_workflow = SELECTED_SYNC_WORKFLOW.read_text(encoding="utf-8")

    def test_migration_is_bounded_and_no_send(self) -> None:
        self.assertIn("Expected exactly one LEAD_ID line.", self.migration_workflow)
        self.assertIn("SMTP_SEND=not_invoked", self.migration_workflow)
        self.assertNotIn("smtplib", self.migration_script)

    def test_fail_closed_legacy_invariants_remain(self) -> None:
        for marker in (
            "expected exactly one sender draft for recipient",
            "existing draft already has a safe Webactueel draft test id; use normal sync",
            "existing legacy draft has unexpected transport marker",
            "existing legacy draft subject does not match OutreachQueue",
            "new migrated draft content readback mismatch",
            "final sender-draft count is",
            "final draft is missing a safe Webactueel draft test id",
            "final migrated draft content does not match OutreachQueue",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.migration_script)

    def test_append_and_readback_happen_before_legacy_delete(self) -> None:
        append_index = self.migration_script.index("new_uid = sync._append")
        readback_index = self.migration_script.index(
            "if not sync._message_matches_queue(imap, new_uid"
        )
        delete_index = self.migration_script.index("sync._delete_uid(imap, old.uid)")
        self.assertLess(append_index, readback_index)
        self.assertLess(readback_index, delete_index)

    def test_selected_batch_requires_exact_final_provider_readback(self) -> None:
        self.assertIn("Expected exactly one EXPECTED_COUNT line.", self.selected_sync_workflow)
        self.assertIn("Expected ${expected_count} LEAD_ID lines", self.selected_sync_workflow)
        self.assertIn(
            "final_readback=${{ steps.command.outputs.expected_count }}",
            self.selected_sync_workflow,
        )
        self.assertIn("smtp_send=not_invoked", self.selected_sync_workflow)
        self.assertIn("SMTP_SEND=not_invoked", self.selected_sync_workflow)


if __name__ == "__main__":
    unittest.main()
