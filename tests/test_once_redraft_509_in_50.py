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
                         ("hold", "insufficient_three_to_six_facts"))

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
                RuntimeError, "^site_research_batch_failed$"
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
