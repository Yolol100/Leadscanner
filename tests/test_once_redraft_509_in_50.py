"""Risk-gated regression tests for existing-only 509-Draft redraft."""
import pathlib
import unittest
from unittest.mock import patch

import _once_redraft_509_in_50 as mod


def row(i):
    return {"lead_id": "growth-" + f"{i:020x}",
            "recipient": f"office{i}@firm{i}.nl",
            "sender": mod.SENDER}


class Existing509RedraftTests(unittest.TestCase):
    def test_initial_509_cohort_is_11_fifty_item_windows(self):
        self.assertEqual(
            [len(list(range(509))[x:x + mod.STEP])
             for x in range(0, mod.TOTAL_ACTIVE, mod.STEP)],
            [50] * 10 + [9],
        )
        self.assertEqual(mod.TOTAL_ACTIVE + mod.TOTAL_HELD, 1173)

    def test_backup_cohort_order_does_not_shift_when_drafts_are_held(self):
        original = [row(i) for i in range(1, 510)]
        active = original[40:]
        held = original[:40] + [row(i) for i in range(510, 1174)]
        client = object()
        with patch.object(mod, "_open_inventory",
                          return_value=("Drafts", active, held)), \
             patch.object(mod, "_find_backup_folder"), \
             patch.object(mod, "_backup_inventory", return_value=original):
            folder, now_active, now_held, cohort = mod._eligible_window(
                client, offset=50
            )
        self.assertEqual(folder, "Drafts")
        self.assertEqual(len(cohort), 50)
        self.assertEqual(cohort[0]["lead_id"], original[50]["lead_id"])
        self.assertEqual(cohort[-1]["lead_id"], original[99]["lead_id"])
        self.assertEqual(len(now_active) + len(now_held), 1173)

    def test_never_overwrite_human_changed_original(self):
        class FakeIMAP:
            def logout(self):
                pass
        client = FakeIMAP()
        candidates = [row(1), row(2)]
        with patch.object(mod, "connect_imap", return_value=client), \
             patch.object(mod, "_eligible_window",
                          return_value=("Drafts", candidates, [], candidates)), \
             patch.object(mod, "_source_context", return_value=({}, {}, [])), \
             patch.object(mod, "_research_window", return_value={
                 candidates[0]["lead_id"]: ("hold", "site_unverified", None),
                 candidates[1]["lead_id"]: ("rewrite", "source_supported", ("x", "y")),
             }), \
             patch.object(mod, "_same_backup", return_value=False), \
             patch.object(mod, "require_uidplus"), \
             patch.object(mod, "ensure_hold_folder"), \
             patch.object(mod, "create_drafts") as writer, \
             patch.object(mod, "move_to_hold") as mover, \
             patch.object(mod, "validate_hold_inventory",
                          return_value=([row(i) for i in range(1, 510)],
                                        [row(i) for i in range(510, 1174)])), \
             patch.object(mod, "_backup_inventory", return_value=candidates):
            report = mod._run_window(0, write=True)
        writer.assert_not_called()
        mover.assert_not_called()
        self.assertEqual(report["counts"]["hold_concurrent_or_user_edit"], 2)
        self.assertEqual(report["emails_sent"], 0)

    def test_excluded_contact_is_not_researched_and_cannot_rewrite(self):
        targets = [row(i) for i in range(1, 4)]
        with patch.object(mod, "source_hint", return_value=("", "", "excluded")), \
             patch.object(mod, "verify_candidates") as verify, \
             patch.object(mod, "research_candidates") as research:
            result = mod._research_window(targets, {}, {}, [])
        self.assertEqual(len(result), 3)
        self.assertTrue(all(choice[0] == "hold" for choice in result.values()))
        verify.assert_not_called()
        research.assert_not_called()

    def test_resume_64_byte_identical_originals_and_copy_only_other_445(self):
        originals = [row(i) for i in range(1, 510)]
        held = [row(i) for i in range(510, 1174)]
        class FakeIMAP:
            def __init__(self):
                self.writes = []
            def uid(self, *args):
                self.writes.append(args)
                return "OK", [b"UID COPY OK"]
            def logout(self):
                pass
        fake = FakeIMAP()
        with patch.object(mod, "connect_imap", return_value=fake), \
             patch.object(mod, "_open_inventory",
                          return_value=("Drafts", originals, held)) as inventory, \
             patch.object(mod, "require_uidplus"), \
             patch.object(mod, "_find_backup_folder"), \
             patch.object(mod, "_backup_inventory",
                          side_effect=[originals[:64], originals]) as backups, \
             patch.object(mod, "_one_uid", return_value=b"101"), \
             patch.object(mod, "_raw_uid", return_value=b"original-exact-raw"), \
             patch.object(mod, "select_folder"):
            outcome = mod._backup_all()
        self.assertEqual(outcome["reused_exact_backups"], 64)
        self.assertEqual(outcome["new_exact_backups"], 445)
        self.assertEqual(outcome["originals_backed_up"], 509)
        self.assertEqual(outcome["mail_sent"], 0)
        self.assertEqual(outcome["mail_replaced"], 0)
        self.assertEqual(len(fake.writes), 445)
        self.assertTrue(all(args[0] == "copy" for args in fake.writes))
        self.assertEqual(inventory.call_count, 2)
        self.assertEqual(backups.call_count, 2)

    def test_partial_original_mismatch_fails_before_any_copy(self):
        originals = [row(i) for i in range(1, 510)]
        held = [row(i) for i in range(510, 1174)]
        class FakeIMAP:
            def __init__(self):
                self.writes = []
            def uid(self, *args):
                self.writes.append(args)
                raise AssertionError("unsafe write attempted")
            def logout(self):
                pass
        fake = FakeIMAP()
        with patch.object(mod, "connect_imap", return_value=fake), \
             patch.object(mod, "_open_inventory",
                          return_value=("Drafts", originals, held)), \
             patch.object(mod, "require_uidplus"), \
             patch.object(mod, "_find_backup_folder"), \
             patch.object(mod, "_backup_inventory", return_value=originals[:64]), \
             patch.object(mod, "_one_uid", return_value=b"101"), \
             patch.object(mod, "_raw_uid",
                          side_effect=[b"current-content", b"old-content"]), \
             patch.object(mod, "select_folder"):
            with self.assertRaisesRegex(RuntimeError, "partial_backup_content_changed"):
                mod._backup_all()
        self.assertEqual(fake.writes, [])

    def test_readonly_all_cohorts_have_exact_50_or_9(self):
        originals = [row(i) for i in range(1, 510)]
        for offset in range(0, 509, mod.STEP):
            with self.subTest(offset=offset):
                window = originals[offset:offset + mod.STEP]
                self.assertEqual(len(window), 9 if offset == 500 else 50)

    def test_backup_fails_before_copy_on_changed_mailbox_inventory(self):
        class FakeIMAP:
            def __init__(self):
                self.writes = []
            def uid(self, *args):
                self.writes.append(args)
                raise AssertionError("unexpected mailbox write")
            def logout(self):
                pass
        client = FakeIMAP()
        with patch.object(mod, "connect_imap", return_value=client), \
             patch.object(mod, "_open_inventory",
                          side_effect=RuntimeError("initial_inventory_509_664_changed")):
            with self.assertRaisesRegex(RuntimeError, "initial_inventory"):
                mod._backup_all()
        self.assertEqual(client.writes, [])

    def test_unqualified_site_never_approves_a_mail(self):
        target = row(1)
        with patch.object(mod, "source_hint", return_value=(
                "https://firm1.nl", "firm1", "")), \
             patch.object(mod, "verify_candidates", return_value={
                 "candidates": [{"lead_id": target["lead_id"], "ready_for_research": True,
                                 "original_recipient": target["recipient"]}]
             }), \
             patch.object(mod, "research_candidates", return_value={
                 "candidates": [{"lead_id": target["lead_id"], "research_status": "ready",
                                 "contact_status": "verified_official_site",
                                 "public_business_email": target["recipient"]}]
             }), \
             patch.object(mod, "rewrite_copy", return_value=("", "")):
            result = mod._research_window([target], {}, {}, [])
        self.assertEqual(result[target["lead_id"]][:2],
                         ("hold", "insufficient_two_to_three_verified_issues"))

    def test_exactly_two_verified_issues_can_be_preview_ready(self):
        target = row(1)
        body = ("1. Eerste bewezen probleem.\n"
                "   Verbeteridee: herstel de interne link.\n"
                "2. Tweede bewezen probleem.\n"
                "   Verbeteridee: voeg een toegankelijk label toe.")
        with patch.object(mod, "source_hint", return_value=(
                "https://firm1.nl", "firm1", "")), \
             patch.object(mod, "verify_candidates", return_value={
                 "candidates": [{"lead_id": target["lead_id"],
                                 "ready_for_research": True}]
             }), \
             patch.object(mod, "research_candidates", return_value={
                 "candidates": [{"lead_id": target["lead_id"],
                                 "research_status": "ready",
                                 "contact_status": "verified_official_site",
                                 "public_business_email": target["recipient"]}]
             }), \
             patch.object(mod, "rewrite_copy", return_value=(
                 "2 technische aandachtspunten", body)), \
             patch.object(mod, "build_message", return_value=(
                 target["lead_id"], object())):
            decisions = mod._research_window([target], {}, {}, [])
        self.assertEqual(decisions[target["lead_id"]][:2],
                         ("rewrite", "source_supported"))

    def test_preview_disconnects_imap_before_external_research(self):
        from unittest.mock import Mock
        client = Mock()
        disconnected = {"value": False}
        client.logout.side_effect = lambda: disconnected.update(value=True)
        active = [row(i) for i in range(1, 510)]
        held = [row(i) for i in range(510, 1174)]

        def website_scan(cohort, *_):
            self.assertTrue(disconnected["value"])
            self.assertEqual(len(cohort), 200)
            return {entry["lead_id"]: ("hold", "site_unverified", None)
                    for entry in cohort}

        with patch.object(mod, "connect_imap", return_value=client), \
             patch.object(mod, "_open_inventory",
                          return_value=("Drafts", active, held)), \
             patch.object(mod, "_source_context", return_value=({}, {}, [])), \
             patch.object(mod, "_research_window", side_effect=website_scan):
            result = mod._preview(0, 200)
        client.logout.assert_called_once()
        self.assertEqual(result["checked"], 200)
        self.assertEqual(result["counts"]["site_unverified"], 200)
        self.assertFalse(result["mailbox_writes"])

    def test_preview_invalid_offset_rejected_without_imap(self):
        with patch.object(mod, "connect_imap") as connection:
            with self.assertRaisesRegex(RuntimeError, "invalid_readonly_preview"):
                mod._preview(100, 200)
        connection.assert_not_called()

    def test_preview_categorizes_source_failure_without_private_details(self):
        client = type("Fake", (), {"logout": lambda self: None})()
        with patch.object(mod, "connect_imap", return_value=client), \
             patch.object(mod, "_open_inventory",
                          return_value=("Drafts", [row(i) for i in range(1, 510)],
                                        [row(i) for i in range(510, 1174)])), \
             patch.object(mod, "_source_context",
                          side_effect=RuntimeError("private provider trace")):
            with self.assertRaisesRegex(
                RuntimeError, "^preview_source_context_failed$"
            ):
                mod._preview(0, 200)

    def test_readonly_backup_reports_partial_without_copy_or_mutation(self):
        from unittest.mock import Mock
        client = Mock()
        first_two = [row(1), row(2)]
        full_active = [row(i) for i in range(1, 510)]
        full_held = [row(i) for i in range(510, 1174)]
        with patch.object(mod, "connect_imap", return_value=client), \
             patch.object(mod, "_open_inventory",
                          return_value=("Drafts", full_active, full_held)), \
             patch.object(mod, "_find_backup_folder") as folder, \
             patch.object(mod, "_backup_inventory",
                          return_value=first_two), \
             patch.object(mod, "_one_uid", return_value=b"17"), \
             patch.object(mod, "select_folder"), \
             patch.object(mod, "_raw_uid", return_value=b"same-original"):
            result = mod._readonly_backup_status()
        self.assertFalse(result["complete"])
        self.assertEqual(result["backup_count"], 2)
        self.assertEqual(result["missing_backup_count"], 507)
        self.assertFalse(result["mailbox_writes"])
        self.assertEqual(result["emails_sent"], 0)
        self.assertEqual(folder.call_args.kwargs["create"], False)
        client.uid.assert_not_called()
        client.logout.assert_called_once()

    def test_readonly_backup_detects_modified_original_and_stops(self):
        from unittest.mock import Mock
        client = Mock()
        with patch.object(mod, "connect_imap", return_value=client), \
             patch.object(mod, "_open_inventory",
                          return_value=("Drafts", [row(i) for i in range(1, 510)],
                                        [row(i) for i in range(510, 1174)])), \
             patch.object(mod, "_find_backup_folder"), \
             patch.object(mod, "_backup_inventory", return_value=[row(1)]), \
             patch.object(mod, "_one_uid", return_value=b"17"), \
             patch.object(mod, "select_folder"), \
             patch.object(mod, "_raw_uid", side_effect=[
                 b"current-version", b"previous-version"]):
            with self.assertRaisesRegex(RuntimeError, "backup_audit_raw_mismatch"):
                mod._readonly_backup_status()
        client.uid.assert_not_called()
        client.logout.assert_called_once()

    def test_unqualified_drafts_stay_active_without_move(self):
        class FakeIMAP:
            def logout(self):
                pass
        targets = [row(1)]
        with patch.object(mod, "connect_imap", return_value=FakeIMAP()), \
             patch.object(mod, "_eligible_window",
                          return_value=("Drafts", targets, [], targets)), \
             patch.object(mod, "_source_context", return_value=({}, {}, [])), \
             patch.object(mod, "_research_window", return_value={
                 targets[0]["lead_id"]: ("hold", "site_unverified", None),
             }), \
             patch.object(mod, "_same_backup", return_value=True), \
             patch.object(mod, "_original_snapshot") as original, \
             patch.object(mod, "_one_address", side_effect=[
                 targets[0]["recipient"], mod.SENDER]), \
             patch.object(mod, "require_uidplus"), \
             patch.object(mod, "ensure_hold_folder") as mkdir, \
             patch.object(mod, "move_to_hold") as mover, \
             patch.object(mod, "create_drafts") as writer, \
             patch.object(mod, "validate_hold_inventory",
                          return_value=([row(i) for i in range(1, 510)],
                                        [row(i) for i in range(510, 1174)])), \
             patch.object(mod, "_backup_inventory", return_value=targets):
            report = mod._run_window(0, write=True)
        self.assertEqual(report["counts"]["unqualified_unchanged"], 1)
        self.assertEqual(report["counts"]["site_unverified"], 1)
        self.assertEqual(report["active_after"], 509)
        original.assert_called_once()
        mkdir.assert_not_called()
        mover.assert_not_called()
        writer.assert_not_called()

    def test_site_research_failure_has_only_safe_reason_code(self):
        target = row(1)
        with patch.object(mod, "source_hint", return_value=(
                "https://firm1.nl", "firm1", "")), \
             patch.object(mod, "verify_candidates", return_value={
                 "candidates": [{"lead_id": target["lead_id"],
                                 "ready_for_research": True}]
             }), \
             patch.object(mod, "research_candidates",
                          side_effect=RuntimeError("sensitive-website.example")):
            with self.assertRaisesRegex(
                RuntimeError, "^all_websites_failed_systemically$"
            ):
                mod._research_window([target], {}, {}, [])

    def test_no_sending_and_no_new_lead_ids_in_one_off(self):
        src = (pathlib.Path(__file__).resolve().parents[1] /
               "scripts/_once_redraft_509_in_50.py").read_text()
        for forbidden in ("smtplib", "sendmail(", "send_message(",
                          "create_new_lead(", "create_campaign(",
                          "client.expunge("):
            self.assertNotIn(forbidden, src)
        self.assertIn("rewrite_existing_only=True", src)
        self.assertIn('LEADSCANNER_AUTHORIZED_509_REDRAFT', src)
        self.assertIn('BACKUP_FOLDER', src)
        self.assertIn('strict_initial=True', src)


if __name__ == "__main__":
    unittest.main()
