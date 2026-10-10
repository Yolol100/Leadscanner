"""No-network contract for exact sender-only source repairs, never sending."""
import copy
import unittest
from unittest.mock import patch

from instantly_campaign_copy import TARGET_CAMPAIGNS
from instantly_signature_repair import (
    normalize_source_first_mail_signatures, _safe_replacement,
)
from myhost_instantly_import import TARGET_LIST_ID

SOURCE_LEAD_ID = "11111111-1111-1111-1111-111111111111"


def fixture(*, lead_id=SOURCE_LEAD_ID, body=None):
    return {
        "id": lead_id, "list_id": TARGET_LIST_ID,
        "email": "private@firm.example", "campaign": None,
        "status": 1, "lt_interest_status": 0, "verification_status": 11,
        "payload": {
            "leadscanner_import_origin": "myhost_drafts",
            "leadscanner_source_lead_id": "growth-" + "a" * 20,
            "leadscanner_contact_basis": "review_required",
            "leadscanner_subject": "Vraag over de website",
            "leadscanner_body": body if body is not None else (
                "Hoi, ik heb een vraag over de afspraakpagina. "
                "Kan ik een voorbeeld sturen? Geen interesse is ook prima."
                "\n\nGroet,\nAndrew\n"
            ),
            "other_review_field": "immutable",
        },
    }


class Provider:
    def __init__(self, rows=None):
        self.rows = [copy.deepcopy(row) for row in (rows or [fixture()])]
        self.calls = []
        self.campaigns = {
            cid: {"id": cid, "name": name, "status": 2, "email_list": []}
            for _, (cid, name) in TARGET_CAMPAIGNS.items()
        }
        self.corrupt_readback = False
        self.stale_get_count = 0
        self.before_patch_snapshot = None

    def get_campaign(self, cid):
        return copy.deepcopy(self.campaigns[cid])

    def list_leads(self, *, campaign=None, limit=100, starting_after=None):
        assert campaign in self.campaigns
        return {"items": [], "next_starting_after": None}

    def get_lead(self, lead_id):
        if self.before_patch_snapshot is not None and self.stale_get_count > 0:
            self.stale_get_count -= 1
            return copy.deepcopy(self.before_patch_snapshot)
        rows = [row for row in self.rows if row["id"] == lead_id]
        if len(rows) != 1:
            raise AssertionError("unexpected lead ID")
        return copy.deepcopy(rows[0])

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path))
        if method != "PATCH" or not path.startswith("/leads/"):
            raise AssertionError("unexpected provider write")
        lead_id = path.removeprefix("/leads/")
        record = next(row for row in self.rows if row["id"] == lead_id)
        self.before_patch_snapshot = copy.deepcopy(record)
        new_fields = copy.deepcopy(kwargs["json"]["custom_variables"])
        if self.corrupt_readback:
            new_fields["other_review_field"] = "corrupted"
        record["payload"] = new_fields
        return {"id": lead_id}


def run(client, **kwargs):
    with patch(
        "instantly_signature_repair.read_imported_leads",
        side_effect=lambda _client: (TARGET_LIST_ID, copy.deepcopy(client.rows)),
    ):
        return normalize_source_first_mail_signatures(
            client, list_id=kwargs.get("list_id", TARGET_LIST_ID),
            expected_count=kwargs.get("expected_count", len(client.rows)),
            max_updates=kwargs.get("max_updates", 1),
            sleep_fn=lambda _: None,
        )


class Tests(unittest.TestCase):
    def test_exact_sender_only_repair_preserves_recipient_and_every_other_variable(self):
        api = Provider()
        original = copy.deepcopy(api.rows[0])
        result = run(api)
        self.assertEqual(result["eligible_before"], 1)
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["remaining_after"], 0)
        self.assertEqual(len(api.calls), 1)
        self.assertTrue(result["all_lead_ids_unchanged"])
        self.assertTrue(result["contact_bases_unchanged"])
        self.assertFalse(result["emails_sent"])
        row = api.rows[0]
        self.assertEqual(row["id"], original["id"])
        self.assertEqual(row["email"], original["email"])
        self.assertEqual(row["list_id"], original["list_id"])
        self.assertIsNone(row["campaign"])
        self.assertEqual(row["payload"]["leadscanner_subject"], original["payload"]["leadscanner_subject"])
        self.assertEqual(row["payload"]["leadscanner_contact_basis"], "review_required")
        self.assertEqual(row["payload"]["other_review_field"], "immutable")
        self.assertEqual(
            row["payload"]["leadscanner_body"],
            original["payload"]["leadscanner_body"].replace("\nAndrew\n", "\nAndrew Baeten\n"),
        )

    def test_replays_do_not_repeat_already_fixed_sender(self):
        api = Provider()
        run(api)
        second = run(api)
        self.assertEqual(second["eligible_before"], 0)
        self.assertEqual(second["updated_count"], 0)
        self.assertEqual(len(api.calls), 1)

    def test_legacy_brand_unknown_tail_or_unverified_origin_are_not_modified(self):
        for body, origin in [
            ("Hoi, ik stuur een voorbeeld. Groet,\nAndrew van " + "Web" + "actueel", "myhost_drafts"),
            ("Hoi, bedankt. Met vriendelijke groet, Nico", "myhost_drafts"),
            ("Hoi, een vraag. Groet,\nAndrew", "unverified_import"),
            ("Hoi, kan ik helpen? Groet,\nAndrew Baeten", "myhost_drafts"),
        ]:
            with self.subTest(body_kind=body[-5:], origin=origin):
                row = fixture(body=body)
                row["payload"]["leadscanner_import_origin"] = origin
                api = Provider([row])
                r = run(api)
                self.assertEqual(r["updated_count"], 0)
                self.assertEqual(api.calls, [])

    def test_bad_source_id_count_or_limit_fails_before_any_write(self):
        api = Provider()
        for opts in (
            {"list_id": "unexpected"},
            {"expected_count": 2},
            {"max_updates": 0},
            {"max_updates": 101},
        ):
            with self.subTest(opts=opts), self.assertRaises((ValueError, RuntimeError)):
                run(api, **opts)
        self.assertFalse(api.calls)

    def test_campaigns_must_be_paused_senderless_and_empty_before_repair(self):
        for mutate in (
            lambda p, cid: p.campaigns[cid].update(status=1),
            lambda p, cid: p.campaigns[cid].update(status=True),
            lambda p, cid: p.campaigns[cid].update(email_list=["sender@example.org"]),
            lambda p, cid: p.campaigns[cid].update(name="unexpected"),
        ):
            api = Provider()
            cid = TARGET_CAMPAIGNS["nl"][0]
            mutate(api, cid)
            with self.assertRaisesRegex(RuntimeError, "requires_paused_campaigns_without_senders"):
                run(api)
            self.assertFalse(api.calls)

    def test_prewrite_source_drift_fails_without_patch(self):
        api = Provider()
        original_get = api.get_lead

        def drift(lead_id):
            result = original_get(lead_id)
            result["payload"]["leadscanner_body"] += " Unexpected reviewer edit."
            return result

        api.get_lead = drift
        with self.assertRaisesRegex(RuntimeError, "copy_changed_before_patch"):
            run(api)
        self.assertEqual(api.calls, [])

    def test_eventually_consistent_postwrite_get_is_reconciled_without_a_second_patch(self):
        api = Provider()
        api.stale_get_count = 3
        result = run(api)
        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(result["remaining_after"], 0)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.stale_get_count, 0)
        self.assertTrue(api.rows[0]["payload"]["leadscanner_body"].rstrip().endswith("Andrew Baeten"))

    def test_postwrite_silent_metadata_corruption_is_detected(self):
        api = Provider()
        api.corrupt_readback = True
        with self.assertRaisesRegex(RuntimeError, "postwrite_mismatch"):
            run(api)
        self.assertEqual(len(api.calls), 1)

    def test_bounded_repair_does_one_eligible_at_a_time(self):
        row2 = fixture(lead_id="22222222-2222-2222-2222-222222222222")
        row2["email"] = "another@firm.example"
        api = Provider([fixture(), row2])
        first = run(api, max_updates=1)
        self.assertEqual(first["updated_count"], 1)
        self.assertEqual(first["remaining_after"], 1)
        second = run(api, max_updates=1)
        self.assertEqual(second["updated_count"], 1)
        self.assertEqual(second["remaining_after"], 0)
        self.assertEqual(len(api.calls), 2)

    def test_control_requires_exact_explicit_bounded_confirmation(self):
        from instantly_control import execute_command, expected_confirmation
        args = {"list_id": TARGET_LIST_ID, "expected_count": 1128, "max_updates": 1}
        action = "repair_imported_first_mail_signatures"
        confirmation = expected_confirmation(action, args)
        self.assertEqual(confirmation, "EXECUTE repair_imported_first_mail_signatures " + TARGET_LIST_ID)
        settings = {
            "schema_version": "leadscanner-instantly-control/1.0",
            "write_actions_enabled": True, "send_actions_enabled": False,
            "destructive_actions_enabled": False, "require_exact_confirmation": True,
        }
        command = {
            "schema_version": "leadscanner-instantly-command/1.0",
            "command_id": "safe-signature-batch-001", "action": action, "args": args,
            "confirm": confirmation, "requested_by": "chatgpt",
        }
        mocked_result = {
            "source_count": 1128, "updated_count": 1, "remaining_after": 1127,
            "emails_sent": False, "contains_email_addresses_or_copy": False,
        }
        with patch("instantly_control.normalize_source_first_mail_signatures",
                   return_value=mocked_result) as repair:
            result = execute_command(command, settings, Provider())
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["result"]["updated_count"], 1)
        self.assertFalse(result["result"]["emails_sent"])
        self.assertEqual(repair.call_args.kwargs["max_updates"], 1)
        with self.assertRaisesRegex(ValueError, "exact_confirmation_required"):
            execute_command({**command, "confirm": "EXECUTE anything"}, settings, Provider())
        with self.assertRaisesRegex(RuntimeError, "write_commands_cannot_run_on_workflow_rerun"):
            execute_command(command, settings, Provider(), run_attempt="2")

    def test_repository_disables_global_send_and_destructive_actions(self):
        import json
        from pathlib import Path
        config_path = Path(__file__).resolve().parents[1] / "config/instantly-control.json"
        settings = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertTrue(settings["write_actions_enabled"])
        self.assertFalse(settings["send_actions_enabled"])
        self.assertFalse(settings["destructive_actions_enabled"])
        self.assertTrue(settings["require_exact_confirmation"])

    def test_normalization_never_overwrites_an_unsigned_body(self):
        value = _safe_replacement({
            "leadscanner_import_origin": "myhost_drafts",
            "leadscanner_contact_basis": "review_required",
            "leadscanner_subject": "Websitevraag",
            "leadscanner_body": "Hoi, bedankt voor je reactie.",
        })
        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
