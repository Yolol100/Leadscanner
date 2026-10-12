import unittest
from unittest.mock import Mock, patch
from requests.exceptions import ReadTimeout

from update_dedupe_registry import (
    HEADERS,
    exact_rows_present,
    plan_registry_update,
    read_live_values,
    update_registry,
    check_registry_access,
)


class RegistryUpdateTests(unittest.TestCase):
    def readback(self, rows):
        return {
            "status": "green",
            "automatic_send": False,
            "draft_count": len(rows),
            "registry_headers": HEADERS,
            "registry_rows": rows,
        }

    def row(self, *, company="Acme Fietsen", domain="acmefietsen.nl", email="info@acmefietsen.nl", lead_id="growth-aaaaaaaaaaaaaaaaaaaa"):
        return [
            company,
            f"https://{domain}/",
            domain,
            email,
            "concept",
            "concept",
            lead_id,
            "",
            "cold_pipeline_review_draft",
            "TRUE",
        ]

    def test_new_row_is_planned_for_append(self):
        current = [HEADERS, self.row(company="Bestaand", domain="bestaand.nl", email="info@bestaand.nl", lead_id="growth-bbbbbbbbbbbbbbbbbbbb")]
        expected = self.row()
        plan = plan_registry_update(self.readback([expected]), current)
        self.assertEqual(plan["append_count"], 1)
        self.assertEqual(plan["existing_count"], 0)
        self.assertEqual(plan["append_rows"], [expected])

    def test_existing_domain_is_not_appended_twice(self):
        expected = self.row()
        current = [HEADERS, expected]
        plan = plan_registry_update(self.readback([expected]), current)
        self.assertEqual(plan["append_count"], 0)
        self.assertEqual(plan["existing_count"], 1)

    def test_existing_email_is_not_appended_twice(self):
        existing = self.row(company="Ander Label", domain="ander.nl", email="info@acmefietsen.nl", lead_id="growth-bbbbbbbbbbbbbbbbbbbb")
        expected = self.row()
        with self.assertRaisesRegex(ValueError, "registry_identity_collision_not_exact"):
            plan_registry_update(self.readback([expected]), [HEADERS, existing])

    def test_company_identity_matches_accent_tolerant_preflight_rules(self):
        existing = self.row(
            company="Café Fietsen B.V.",
            domain="ander.nl",
            email="other@ander.nl",
            lead_id="growth-bbbbbbbbbbbbbbbbbbbb",
        )
        expected = self.row(
            company="Cafe Fietsen BV",
            domain="nieuw.nl",
            email="new@nieuw.nl",
            lead_id="growth-cccccccccccccccccccc",
        )
        with self.assertRaisesRegex(ValueError, "registry_identity_collision_not_exact"):
            plan_registry_update(self.readback([expected]), [HEADERS, existing])

    def test_subdomain_identity_matches_preflight_domain_rules(self):
        existing = self.row(
            company="Ander Label",
            domain="shop.acmefietsen.nl",
            email="other@shop.acmefietsen.nl",
            lead_id="growth-bbbbbbbbbbbbbbbbbbbb",
        )
        expected = self.row(
            company="Nieuw Label",
            domain="acmefietsen.nl",
            email="new@acmefietsen.nl",
            lead_id="growth-cccccccccccccccccccc",
        )
        with self.assertRaisesRegex(ValueError, "registry_identity_collision_not_exact"):
            plan_registry_update(self.readback([expected]), [HEADERS, existing])

    def test_existing_domain_same_lead_id_but_changed_status_is_not_exact(self):
        existing = self.row()
        existing[4] = "sent"
        expected = self.row()
        with self.assertRaisesRegex(ValueError, "registry_identity_collision_not_exact"):
            plan_registry_update(self.readback([expected]), [HEADERS, existing])

    def test_two_new_drafts_colliding_on_domain_are_rejected(self):
        one = self.row()
        two = self.row(email="another@acmefietsen.nl", lead_id="growth-cccccccccccccccccccc")
        with self.assertRaisesRegex(ValueError, "registry_identity_collision_not_exact"):
            plan_registry_update(self.readback([one, two]), [HEADERS])

    def test_existing_identity_without_suppression_fails_closed(self):
        existing = self.row()
        existing[9] = "FALSE"
        expected = self.row()
        with self.assertRaisesRegex(ValueError, "identity_exists_without_suppression"):
            plan_registry_update(self.readback([expected]), [HEADERS, existing])

    def test_registry_requires_true_suppression_flag(self):
        expected = self.row()
        expected[9] = "FALSE"
        with self.assertRaisesRegex(ValueError, "must_suppress"):
            plan_registry_update(self.readback([expected]), [HEADERS])

    def test_exact_readback_requires_full_appended_row(self):
        expected = self.row()
        self.assertTrue(exact_rows_present([expected], [HEADERS, expected]))
        changed = list(expected)
        changed[4] = "sent"
        self.assertFalse(exact_rows_present([expected], [HEADERS, changed]))

    def test_zero_draft_still_validates_readback_contract(self):
        invalid_status = self.readback([])
        invalid_status["status"] = "red"
        with self.assertRaisesRegex(ValueError, "readback_must_be_green"):
            update_registry(invalid_status, spreadsheet_id="sheet", sheet_name="tab")

        inconsistent = self.readback([self.row()])
        inconsistent["draft_count"] = 0
        with self.assertRaisesRegex(ValueError, "registry_intent_count_mismatch"):
            update_registry(inconsistent, spreadsheet_id="sheet", sheet_name="tab")

    def test_bad_live_headers_fail_closed(self):
        expected = self.row()
        with self.assertRaisesRegex(ValueError, "live_registry_headers_mismatch"):
            plan_registry_update(self.readback([expected]), [["company", "domain"]])


    def test_registry_access_preflight_does_not_mutate_headers(self):
        client = Mock()
        with patch("update_dedupe_registry._authorized_session", return_value=(client, "redacted")), \
             patch("update_dedupe_registry.read_live_values", return_value=[HEADERS, self.row()]):
            result = check_registry_access(spreadsheet_id="test", sheet_name="DedupeRegistry")
        self.assertEqual(result["write_intent"], "read_verified_write_unproven")
        client.put.assert_not_called()
        client.post.assert_not_called()

    def test_registry_closure_rechecks_previously_existing_exact_identity(self):
        expected = self.row()
        changed = list(expected)
        changed[4] = "sent"
        client = Mock()
        with patch("update_dedupe_registry._authorized_session", return_value=(client, "redacted")), \
             patch("update_dedupe_registry.read_live_values",
                   side_effect=[[HEADERS, expected], [HEADERS, changed]]), \
             patch("update_dedupe_registry.append_values") as appended:
            with self.assertRaisesRegex(RuntimeError, "registry_exact_readback_mismatch"):
                update_registry(self.readback([expected]), spreadsheet_id="test", sheet_name="DedupeRegistry")
        appended.assert_called_once()
        self.assertEqual(appended.call_args.args[-1], [])

    def test_readonly_registry_get_retries_one_sheets_timeout(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": [HEADERS]}
        session.get.side_effect = [ReadTimeout("simulated"), response]
        pauses = []
        values = read_live_values(session, "sheet", "DedupeRegistry", sleep_fn=pauses.append)
        self.assertEqual(values, [HEADERS])
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(pauses, [1])
        session.post.assert_not_called()
        session.put.assert_not_called()

    def test_readonly_registry_get_fails_closed_after_three_timeouts(self):
        session = Mock()
        session.get.side_effect = ReadTimeout("simulated")
        pauses = []
        with self.assertRaisesRegex(RuntimeError, "registry_read_transient_retries_exhausted"):
            read_live_values(session, "sheet", "DedupeRegistry", sleep_fn=pauses.append)
        self.assertEqual(session.get.call_count, 3)
        self.assertEqual(pauses, [1, 2])
        session.post.assert_not_called()
        session.put.assert_not_called()

    def test_registry_permission_failure_does_not_retry(self):
        session = Mock()
        session.get.return_value.status_code = 403
        pauses = []
        with self.assertRaisesRegex(RuntimeError, "registry_read_failed status=403"):
            read_live_values(session, "sheet", "DedupeRegistry", sleep_fn=pauses.append)
        self.assertEqual(session.get.call_count, 1)
        self.assertEqual(pauses, [])
        session.post.assert_not_called()
        session.put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
