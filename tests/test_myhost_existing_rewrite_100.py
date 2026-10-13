"""Synthetic evidence for approved 100-Draft rewrite; no live mail or recipient data."""
from __future__ import annotations
import os
import unittest
from unittest.mock import patch
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default

import _once_myhost_existing_rewrite as target
from myhost_draft import create_drafts, lead_id_from_message
from test_myhost_draft import FakeIMAP, DraftTests


class FakeHeaderClient:
    def __init__(self, amount=1173):
        self.amount = amount
        self.readonly = []
        self.raw = {}
        for i in range(1, amount + 1):
            tag = f"growth-{i:020x}"
            self.raw[i] = (
                f"From: Andrew Baeten <info@andrewbaeten.nl>\r\n"
                f"To: hello{i}@brand{i}.nl\r\n"
                f"X-Leadscanner-Lead-ID: {tag}\r\n"
                f"X-Leadscanner-Review-Required: contact-basis\r\n\r\n"
            ).encode()
    def select(self, mailbox, readonly=True):
        self.readonly.append(readonly)
        return "OK", [str(self.amount).encode()]
    def search(self, charset, *args):
        if args[1] == "X-Leadscanner-Lead-ID":
            return "OK", [b" ".join(str(i).encode() for i in range(1, self.amount + 1))]
        return "OK", [b""]
    def fetch(self, seq, command):
        assert "BODY.PEEK[HEADER" in command
        return "OK", [(b"RFC822", self.raw[int(i)]) for i in seq.split(",")]


class ExistingRewriteTests(unittest.TestCase):
    def test_anonymous_hold_categories_are_closed_vocabulary(self):
        self.assertEqual(len(target.SOURCE_HOLD_REASONS), 6)
        self.assertIn("historically_contacted_or_blocked", target.SOURCE_HOLD_REASONS)
        self.assertIn("hold_robots_policy", target.SITE_HOLD_STATUSES)
        self.assertNotIn("email", target.SITE_HOLD_STATUSES)

    def test_stable_inventory_exact_1173_and_100_windows(self):
        client = FakeHeaderClient()
        ordered = target.inventory_existing(client, "Drafts")
        self.assertEqual(len(ordered), target.EXPECTED_TAGGED_DRAFTS)
        self.assertEqual(ordered[0]["lead_id"], "growth-" + f"{1:020x}")
        self.assertTrue(all(client.readonly))
        self.assertEqual(
            [len(ordered[offset:offset + 100]) for offset in range(0, 1173, 100)],
            [100]*11 + [73],
        )

    def test_tagged_mailbox_drift_blocks_before_any_write(self):
        with self.assertRaisesRegex(RuntimeError, "imap_tagged_baseline_changed"):
            target.inventory_existing(FakeHeaderClient(1172), "Drafts")

    def test_unverified_public_provider_without_source_is_held(self):
        site, company, error = target.source_hint(
            {"lead_id": "growth-" + "a"*20, "recipient": "owner@gmail.com"},
            {}, {"status": "historical_v2_suppression"}, [])
        self.assertFalse(site)
        self.assertFalse(company)
        self.assertEqual(error, "no_verified_shared_mail_provider_site")

    def test_previously_contacted_historical_recipient_held(self):
        source = {"status": -2}
        with patch.object(target, "excluded_history", return_value=True):
            site, company, error = target.source_hint(
                {"lead_id": "growth-" + "a"*20, "recipient": "hello@site.nl"},
                {"hello@site.nl": source}, {}, [])
        self.assertEqual(error, "historically_contacted_or_blocked")

    def test_current_public_corporate_mail_may_be_visited_as_hypothesis(self):
        site, name, error = target.source_hint(
            {"lead_id": "growth-" + "a"*20, "recipient": "hello@fonteinonline.nl"},
            {}, {"status": "historical_v2_suppression"}, [])
        self.assertEqual(error, "")
        self.assertEqual(site, "https://fonteinonline.nl")
        self.assertEqual(name, "fonteinonline")

    def test_dutch_copy_uses_verified_point_and_exact_signoff(self):
        base = {
            "official_domain": "voorbeeld.nl",
            "language": "nl",
        }
        obs = "Op de contactpagina is een online offerteaanvraag beschikbaar."
        finding = {"source_type": "official_site", "source_url": "https://voorbeeld.nl/contact",
                   "observation": obs}
        ranked = {"outreach_status": "ready", "selected_findings": [finding],
                  "verified_observation": obs,
                  "verified_observation_source_url": finding["source_url"],
                  "verified_observation_source_type": "official_site"}
        prepared = {"language": "nl", "value_action_status": "proposed"}
        generated = {
            "mail_status": "ready_for_human_review", "copy_validation_status": "green",
            "language": "nl", "subject": "idee voor jullie offerteaanvraag",
            "body": ("Hoi,\n\nOp de contactpagina is een online offerteaanvraag beschikbaar.\n\n"
                     "Kan ik een kleine voorbeeldverbetering sturen?\n\nGroet,\nAndrew Baeten"),
        }
        with patch.object(target, "select_one_reason", return_value=ranked), \
             patch.object(target, "value_action_for", return_value=prepared), \
             patch.object(target, "generate_one_mail", return_value=generated):
            subject, body = target.rewrite_copy(base)
        self.assertEqual(subject, "idee voor jullie offerteaanvraag")
        self.assertIn(obs, body)
        self.assertTrue(body.endswith("Met vriendelijke groeten,\nAndrew"))
        self.assertNotIn("Andrew Baeten", body)

    def test_english_signoff_and_no_synthetic_facts(self):
        obs = "Visitors can request a quote using the online form."
        finding = {"source_type": "official_site", "source_url": "https://example.org/contact",
                   "observation": obs}
        result = {
            "mail_status": "ready_for_human_review", "copy_validation_status": "green",
            "language": "en", "subject": "idea for your quote flow",
            "body": "Hi,\n\n"+obs+"\n\nCan I share an example?\n\nBest,\nAndrew Baeten",
        }
        with patch.object(target, "select_one_reason", return_value={
                "outreach_status": "ready", "selected_findings": [finding]}), \
             patch.object(target, "value_action_for", return_value={}), \
             patch.object(target, "generate_one_mail", return_value=result):
            _, body = target.rewrite_copy({"official_domain":"example.org"})
        self.assertTrue(body.endswith("Kind regards,\nAndrew"))
        self.assertIn(obs, body)

    def test_nonofficial_evidence_never_leads_to_email(self):
        with patch.object(target, "select_one_reason", return_value={
            "outreach_status": "ready",
            "selected_findings": [{
                "source_type": "web_search",
                "source_url": "https://other.org",
                "observation": "Unverified copied line",
            }]}):
            self.assertEqual(target.rewrite_copy({"official_domain": "example.org"}), ("", ""))

    def test_existing_only_rewrite_changes_review_marker_and_preserves_recipient(self):
        client = FakeIMAP()
        original = DraftTests().row()
        original["status"] = "draft_ready"
        original["contact_basis_status"] = "pass"
        with patch("myhost_draft.connect_imap", return_value=client):
            first = create_drafts({"rows": [original]}, reject_changed_existing=True)
        self.assertEqual(first["created_count"], 1)
        updated = dict(original, status="review_draft",
                       contact_basis_status="review_required",
                       subject="idee voor jullie afspraakroute",
                       body="Hoi,\n\nVerifieerbare observatie.\n\nMet vriendelijke groeten,\nAndrew")
        with patch("myhost_draft.connect_imap", return_value=client):
            result = create_drafts({"rows": [updated]}, rewrite_existing_only=True)
        self.assertEqual(result["created_count"], 0)
        self.assertEqual(result["replaced_count"], 1)
        self.assertEqual(len(client.messages), 1)
        actual = BytesParser(policy=default).parsebytes(client.messages[0])
        self.assertEqual(actual["To"], original["email"])
        self.assertEqual(lead_id_from_message(actual), original["lead_id"])
        self.assertEqual(actual["Subject"], updated["subject"])

    def test_rewrite_existing_only_never_creates_missing_draft(self):
        original = DraftTests().row()
        client = FakeIMAP()
        with patch("myhost_draft.connect_imap", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "exactly one existing draft"):
                create_drafts({"rows": [original]}, rewrite_existing_only=True)
        self.assertEqual(client.append_calls, 0)

    def test_mailbox_writes_never_use_smtp_module(self):
        import inspect
        program = inspect.getsource(target)
        self.assertNotIn("smtplib", program)
        self.assertNotIn("send_message", program)
        self.assertNotIn("sendmail(", program)


    def test_three_review_required_drafts_require_explicit_gate(self):
        with patch.dict(os.environ, {"LEADSCANNER_HOLD_REVISION": "false"}):
            with self.assertRaisesRegex(RuntimeError, "revision_holding_not_authorized"):
                target.run(500, write=False, cleanup=True, hold_revision=True)
        with patch.dict(os.environ, {"LEADSCANNER_HOLD_REVISION": "true"}):
            with self.assertRaisesRegex(RuntimeError, "revision_holding_not_authorized"):
                target.run(300, write=False, cleanup=True, hold_revision=True)

    def test_exact_five_draft_hold_reason_counts_and_inventory(self):
        from collections import Counter
        first = Counter({
            "checked": 62, "already_correct": 58, "researched": 60,
            "ready_to_rewrite": 1, "hold_site_verification": 2,
            "site_hold_hold_robots_policy": 2,
            "hold_contact_not_currently_published": 1,
        })
        targets = {"a": "site", "b": "site", "c": "address", "d": "revision"}
        accepted = target._verify_revision_evidence(500, [None] * 62, first, targets)
        self.assertEqual((accepted["expected_moves"], accepted["active_after"],
                          accepted["held_after"]), (4, 505, 668))
        second = Counter({
            "checked": 65, "already_correct": 64, "researched": 65,
            "ready_to_rewrite": 1,
        })
        accepted = target._verify_revision_evidence(
            1000, [None] * 65, second, {"e": "revision"})
        self.assertEqual((accepted["expected_moves"], accepted["active_after"],
                          accepted["held_after"]), (1, 504, 669))

    def test_exact_five_draft_hold_fails_closed_on_any_changed_evidence(self):
        from collections import Counter
        good = Counter({
            "checked": 62, "already_correct": 58, "researched": 60,
            "ready_to_rewrite": 1, "hold_site_verification": 2,
            "site_hold_hold_robots_policy": 2,
            "hold_contact_not_currently_published": 1,
        })
        targets = {"a": "site", "b": "site", "c": "address", "d": "revision"}
        cases = [
            (Counter(dict(good, hold_contact_not_currently_published=0)), targets),
            (Counter(dict(good, hold_contact_not_currently_published=2)), targets),
            (Counter(dict(good, already_correct=59)), targets),
            (Counter(dict(good, site_hold_hold_robots_policy=1)), targets),
            (Counter(dict(good, hold_insufficient_evidence_or_copy=1)), targets),
            (good, {"a": "site", "b": "site", "c": "address", "d": "address"}),
            (good, {"a": "site", "b": "site", "c": "address"}),
        ]
        for observed, held in cases:
            with self.subTest(observed=dict(observed), reasons=held):
                with self.assertRaisesRegex(RuntimeError, "five_draft_evidence_drift"):
                    target._verify_revision_evidence(500, [None] * 62, observed, held)
        with self.assertRaisesRegex(RuntimeError, "five_draft_evidence_drift"):
            target._verify_revision_evidence(
                1000, [None] * 65,
                Counter({"checked": 65, "already_correct": 65,
                         "researched": 65}), {})


if __name__ == "__main__":
    unittest.main()
