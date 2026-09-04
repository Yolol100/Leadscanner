import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_extended_preflight as p


class OutreachExtendedPreflightTests(unittest.TestCase):
    def test_sequence_requires_matching_queue_row(self):
        errors = p.validate_queue_sequence_alignment([], [{"lead_id": "lead-1", "enabled": "true"}])
        self.assertTrue(any("no matching OutreachQueue" in item for item in errors))

    def test_prepared_sequence_queue_state_fails_closed(self):
        errors = p.validate_queue_sequence_alignment(
            [{"lead_id": "lead-1", "status": "prepared"}],
            [{"lead_id": "lead-1", "enabled": "true"}],
        )
        self.assertTrue(any("not transport-approved" in item for item in errors))

    def test_approved_and_later_lifecycle_states_are_allowed(self):
        for state in ("approved", "verification_pending", "sent", "sequence_complete", "replied"):
            with self.subTest(state=state):
                errors = p.validate_queue_sequence_alignment(
                    [{"lead_id": "lead-1", "status": state}],
                    [{"lead_id": "lead-1", "enabled": "true"}],
                )
                self.assertEqual(errors, [])

    def test_duplicate_queue_lead_id_is_rejected(self):
        errors = p.validate_queue_sequence_alignment(
            [{"lead_id": "lead-1", "status": "approved"}, {"lead_id": "lead-1", "status": "approved"}],
            [{"lead_id": "lead-1", "enabled": "true"}],
        )
        self.assertTrue(any("duplicate lead_id" in item for item in errors))

    def test_disabled_sequence_row_does_not_require_queue_row(self):
        errors = p.validate_queue_sequence_alignment([], [{"lead_id": "lead-1", "enabled": "false"}])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
