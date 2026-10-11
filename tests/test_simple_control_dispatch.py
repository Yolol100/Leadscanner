"""The simplified read-only Instantly dispatcher must never reach mutation gates."""
import unittest
from unittest.mock import patch

import instantly_control as control


class SimpleInstantlyAuditsTests(unittest.TestCase):
    def test_every_passive_audit_still_has_a_direct_non_send_route(self):
        mapping = {
            "audit_two_campaign_options": "audit_two_campaign_options",
            "audit_retired_archive": "audit_retired_archive",
            "audit_old_archive_metadata": "audit_old_archive_metadata",
            "audit_imported_mail_quality": "mail_quality_audit",
            "audit_synthetic_campaign_previews": "audit_synthetic_campaign_previews",
            "audit_old_archive_state": "audit_old_archive_state",
            "audit_old_campaign_retirement": "audit_old_campaign_retirement",
            "audit_sender_vitals": "audit_sender_vitals",
            "audit_launch_inventory": "audit_launch_inventory",
            "audit_language_split": "audit_language_split",
        }
        for action, function in mapping.items():
            with self.subTest(action=action), patch.object(
                control, function, return_value={"verified": True}
            ) as spy:
                client = object()
                command = {"action": action, "args": {}, "command_id": "simple-audit"}
                result = control.execute_command(command, {}, client)
                spy.assert_called_once_with(client)
                self.assertEqual(result["action"], action)
                self.assertEqual(result["mode"], "read")
                self.assertFalse(result["send_action"])
                self.assertFalse(result["destructive_action"])
                self.assertEqual(result["result"], {"verified": True})


if __name__ == "__main__":
    unittest.main()
