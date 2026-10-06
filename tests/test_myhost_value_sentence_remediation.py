from __future__ import annotations

import unittest
from unittest.mock import patch
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default

from myhost_value_sentence_remediation import (
    EN_GENERAL,
    NL_GENERAL,
    analyze_body,
    build_audit,
    decrypt_state,
    encrypt_state,
    full_snapshot,
    message_with_body,
    verify_or_apply,
)


NL_BODY = """Hallo,

Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden.

Met mijn Groeiabonnement kan ik meerdere onderdelen van jullie online aanpak oppakken:

• Website/webshop — verbeteren of nieuw maken waar nodig
• Zoekbaarheid — beter vindbaar worden
• Social content — passende content
• Automatisering — geschikte processen deels automatiseren waar haalbaar
• Hosting — beheren of overnemen waar passend
• Ik als vast contactpersoon

€250–€500 per maand, afhankelijk van wat jullie nodig hebben.

Zal ik vrijblijvend een voorbeeld design maken voor Voorbeeld Fysiotherapie? Dan kunnen jullie eerst bekijken of de richting interessant is.

Geen interesse? Laat het gerust weten.

Groet,
Andrew"""

EN_BODY = """Hello,

I saw on your website that you provide physical therapy in Utrecht.

My Growth Subscription covers several parts of your online presence:

• Website/webshop — improve or build new where needed
• Search visibility — improve findability
• Social content — relevant content
• Automation — partially automate suitable processes where feasible
• Hosting — manage or take over where appropriate
• Me as your fixed point of contact

€250–€500 per month, depending on what you need.

Would you like me to make a no-obligation example design for Example Physiotherapy, so you can first see whether the direction is relevant?

Not interested? Just let me know.

Regards,
Andrew"""


class ValueSentenceRemediationTests(unittest.TestCase):
    def message(self, body=NL_BODY):
        msg = EmailMessage(policy=default)
        msg["From"] = "Andrew Baeten <info@andrewbaeten.nl>"
        msg["To"] = "info@example.nl"
        msg["Subject"] = "Idee voor Voorbeeld Fysiotherapie"
        msg["X-Webactueel-Lead-ID"] = "growth-" + "a" * 20
        msg["X-Webactueel-Review-Required"] = "contact-basis"
        msg["X-Webactueel-Test-Metadata"] = "preserve-me"
        msg.set_content(body)
        return msg

    def test_nl_value_sentence_is_upgraded_from_verified_opening(self):
        result = analyze_body(NL_BODY)
        self.assertEqual(result["language"], "nl")
        self.assertTrue(result["tailored"])
        self.assertEqual(
            result["expected_value"],
            "Voor fysiotherapie en revalidatie brengt mijn Groeiabonnement website, vindbaarheid, content, automatisering en hosting samen met één vast aanspreekpunt:",
        )
        self.assertNotIn(NL_GENERAL, result["expected_body"])
        self.assertIn("• Website/webshop — verbeteren of nieuw maken waar nodig", result["expected_body"])
        self.assertIn("€250–€500 per maand", result["expected_body"])
        self.assertIn("Zal ik vrijblijvend een voorbeeld design maken voor", result["expected_body"])

    def test_en_value_sentence_is_upgraded(self):
        result = analyze_body(EN_BODY)
        self.assertEqual(result["language"], "en")
        self.assertTrue(result["tailored"])
        self.assertEqual(
            result["expected_value"],
            "For physical therapy and rehabilitation, my Growth Subscription brings website, search visibility, content, automation and hosting together with one fixed point of contact:",
        )
        self.assertNotIn(EN_GENERAL, result["expected_body"])

    def test_unknown_focus_keeps_safe_general_sentence(self):
        body = NL_BODY.replace(
            "Ik zag op jullie website dat jullie fysiotherapie in Utrecht aanbieden.",
            "Ik zag op jullie website dat jullie industriële componenten leveren.",
        )
        result = analyze_body(body)
        self.assertFalse(result["tailored"])
        self.assertEqual(result["expected_value"], NL_GENERAL)
        self.assertEqual(result["expected_body"], body)

    def test_legacy_value_sentence_in_canonical_slot_is_migrated(self):
        legacy = NL_BODY.replace(
            NL_GENERAL,
            "Met één compact Groeiabonnement kan ik deze online onderdelen voor jullie combineren:",
        )
        result = analyze_body(legacy)
        self.assertTrue(result["tailored"])
        self.assertNotIn("compact Groeiabonnement", result["expected_body"])
        self.assertIn(
            "Voor fysiotherapie en revalidatie brengt mijn Groeiabonnement website, vindbaarheid, content, automatisering en hosting samen met één vast aanspreekpunt:",
            result["expected_body"],
        )

    def test_empty_or_broken_value_slot_fails_closed(self):
        bad = NL_BODY.replace(NL_GENERAL + "\n\n", "\n\n")
        with self.assertRaisesRegex(ValueError, "unsupported_growth_layout"):
            analyze_body(bad)

    def test_missing_bullet_fails_closed(self):
        bad = NL_BODY.replace(
            "• Hosting — beheren of overnemen waar passend\n",
            "",
        )
        with self.assertRaisesRegex(ValueError, "canonical_six_bullets_missing"):
            analyze_body(bad)

    def test_message_replacement_preserves_identity_and_custom_headers(self):
        current = self.message()
        result = analyze_body(NL_BODY)
        expected = message_with_body(current, result["expected_body"])
        snapshot = full_snapshot(expected)
        self.assertEqual(snapshot["to"], "info@example.nl")
        self.assertEqual(snapshot["subject"], "Idee voor Voorbeeld Fysiotherapie")
        self.assertEqual(snapshot["lead_id"], "growth-" + "a" * 20)
        self.assertEqual(snapshot["review_status"], "contact-basis")
        self.assertIn(
            ["x-webactueel-test-metadata", "preserve-me"],
            snapshot["x_headers"],
        )
        self.assertIn(result["expected_value"], snapshot["body"])

    def test_folded_metadata_header_is_unfolded_and_preserved(self):
        current = self.message()
        current.replace_header(
            "X-Webactueel-Test-Metadata",
            "metadata-" + ("x" * 220),
        )
        parsed = BytesParser(policy=default).parsebytes(current.as_bytes(policy=default))
        result = analyze_body(NL_BODY)
        expected = message_with_body(parsed, result["expected_body"])
        before_headers = full_snapshot(parsed)["x_headers"]
        after_headers = full_snapshot(expected)["x_headers"]
        self.assertEqual(after_headers, before_headers)
        self.assertIn(
            ["x-webactueel-review-required", "contact-basis"],
            after_headers,
        )

    def test_audit_bulk_fetches_selected_messages_and_reports_capabilities(self):
        lead_id = "growth-" + "a" * 20
        msg = self.message()

        class AuditClient:
            capabilities = (b"IMAP4REV1", b"UIDPLUS", b"MULTIAPPEND")
            def logout(self):
                return "BYE", []

        client = AuditClient()
        with patch(
            "myhost_value_sentence_remediation.connect_imap",
            return_value=client,
        ), patch(
            "myhost_value_sentence_remediation.find_drafts_folder",
            return_value="Drafts",
        ), patch(
            "myhost_value_sentence_remediation.growth_uid_index",
            return_value=[(lead_id, b"10")],
        ), patch(
            "myhost_value_sentence_remediation.bulk_fetch_uid_messages",
            return_value={b"10": msg},
        ) as bulk_fetch, patch(
            "myhost_value_sentence_remediation.fetch_message_uid",
            side_effect=AssertionError("audit must not fetch selected messages one by one"),
        ):
            state, summary = build_audit(0, 1)

        bulk_fetch.assert_called_once_with(client, [b"10"])
        self.assertEqual(len(state["items"]), 1)
        self.assertTrue(summary["uidplus_available"])
        self.assertTrue(summary["multiappend_available"])
        self.assertEqual(summary["blocker_count"], 0)

    def test_apply_uses_multiappend_for_multiple_pending_drafts(self):
        lead_a = "growth-" + "5" * 20
        lead_b = "growth-" + "6" * 20

        def make_message(lead_id):
            msg = self.message()
            msg.replace_header("X-Webactueel-Lead-ID", lead_id)
            return msg

        old_a = make_message(lead_a)
        old_b = make_message(lead_b)
        expected_body = analyze_body(NL_BODY)["expected_body"]
        expected_a = message_with_body(old_a, expected_body)
        expected_b = message_with_body(old_b, expected_body)

        state = {
            "version": "leadscanner-value-sentence-state-v1",
            "expires_at_epoch": 9999999999,
            "items": [
                {
                    "lead_id": lead_a,
                    "status": "ready",
                    "action": "replace",
                    "before": full_snapshot(old_a),
                    "expected": full_snapshot(expected_a),
                },
                {
                    "lead_id": lead_b,
                    "status": "ready",
                    "action": "replace",
                    "before": full_snapshot(old_b),
                    "expected": full_snapshot(expected_b),
                },
            ],
        }

        initial = {
            lead_a: {"uids": [b"10"], "messages": [old_a]},
            lead_b: {"uids": [b"20"], "messages": [old_b]},
        }
        final = {
            lead_a: {"uids": [b"30"], "messages": [expected_a]},
            lead_b: {"uids": [b"31"], "messages": [expected_b]},
        }

        class ApplyClient:
            capabilities = (b"IMAP4REV1", b"UIDPLUS", b"MULTIAPPEND")
            def logout(self):
                return "BYE", []

        client = ApplyClient()
        with patch(
            "myhost_value_sentence_remediation.connect_imap",
            return_value=client,
        ), patch(
            "myhost_value_sentence_remediation.find_drafts_folder",
            return_value="Drafts",
        ), patch(
            "myhost_value_sentence_remediation.bulk_inventory_drafts",
            side_effect=[initial, final, final],
        ), patch(
            "myhost_value_sentence_remediation.replace_known_drafts_multiappend_and_verify",
            return_value=[
                {"lead_id": lead_a, "new_uid": b"30", "message": expected_a},
                {"lead_id": lead_b, "new_uid": b"31", "message": expected_b},
            ],
        ) as multiappend, patch(
            "myhost_value_sentence_remediation.replace_known_draft_and_verify",
            side_effect=AssertionError("single replacement should not run"),
        ):
            summary = verify_or_apply(state, "apply")

        self.assertEqual(multiappend.call_count, 1)
        self.assertTrue(summary["multiappend_used"])
        self.assertEqual(summary["multiappend_shards"], 1)
        self.assertEqual(summary["multiappend_shard_size"], 50)
        self.assertEqual(summary["changed_count"], 2)
        self.assertEqual(summary["verified_count"], 2)

    def test_encrypted_state_roundtrip_and_tamper_rejection(self):
        payload = {"items": [{"lead_id": "growth-" + "b" * 20}], "version": "x"}
        secret = "test-secret"
        repo = "Yolol100/Leadscanner"
        envelope = encrypt_state(payload, secret, repo)
        self.assertEqual(decrypt_state(envelope, secret, repo), payload)
        broken = dict(envelope)
        broken["ciphertext"] = broken["ciphertext"][:-2] + "AA"
        with self.assertRaises(Exception):
            decrypt_state(broken, secret, repo)


if __name__ == "__main__":
    unittest.main()
