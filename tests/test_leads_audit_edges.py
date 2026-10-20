"""Audit-only synthetic edge cases for the four-step Leads flow."""
import unittest
from unittest.mock import Mock, patch

import draft_queue_readonly as queue
import myhost_draft as draft
from target_scope import (
    ALLOWED_REQUEST_KEYWORDS,
    REQUEST_CATEGORY_ALIASES,
    normalize,
)

ROW = {
    "draft_id": "draft-0123456789abcdef0123456789abcdef",
    "created_at": "2026-10-14T18:00:00+02:00",
    "company": "Fictief Schildersbedrijf",
    "email": "info@fictief-schildersbedrijf.nl",
    "source_url": "https://fictief-schildersbedrijf.nl/contact",
    "subject": "Vraag over Fictief Schildersbedrijf",
    "body": "Goedendag,\n\nIk zag dat jullie schilderwerk aanbieden.\n\nZou het handig zijn als klanten hun wensen vooraf kunnen doorgeven?\n\nLiever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij.\n\nGroet,\nAndrew",
}


class LocalIndustryCoverageAudit(unittest.TestCase):
    def test_every_allowed_trade_has_an_overture_taxonomy_alias(self):
        normalized = {normalize(key) for key in REQUEST_CATEGORY_ALIASES}
        missing = sorted(keyword for keyword in ALLOWED_REQUEST_KEYWORDS
                         if normalize(keyword) not in normalized)
        self.assertEqual(missing, [], "Allowed target terms without taxonomy coverage")

    def test_key_trades_match_precise_taxonomy_not_every_service(self):
        from overture_discovery import _matches_keywords
        fixtures = (
            ("rietdekker", "roofing_contractor"),
            ("sanitairinstallateur", "plumber"),
            ("gevelreiniging", "building_cleaning_service"),
            ("fietswinkel", "bicycle_store"),
        )
        for term, category in fixtures:
            with self.subTest(term=term):
                place = {"names": {"primary": "Onbenoemd Lokaal Bedrijf"},
                         "basic_category": category}
                self.assertTrue(_matches_keywords(place, [term]))


class DraftReadOnlyValidationAudit(unittest.TestCase):
    def test_malformed_emails_are_rejected(self):
        for email in ("x@@voorbeeld.nl", "zonder-domein@localhost", "naam@voorbeeld..nl",
                      "naam@-voorbeeld.nl", "naam@voorbeeld.nl,cc@ander.nl",
                      "a@voorbeeld", "name<>@voorbeeld.nl"):
            with self.subTest(email=email), patch(
                "draft_queue_readonly.is_public_http_url", return_value=True
            ):
                item = dict(ROW, email=email)
                with self.assertRaises(RuntimeError):
                    queue._validate_row(item)

    def test_unresolved_template_placeholders_rejected(self):
        for updates in (
            {"subject": "Website [Bedrijf]"},
            {"body": "Hoi [Bedrijf],\nGroet [Naam]\nWebactueel"},
        ):
            with self.subTest(updates=updates), patch(
                "draft_queue_readonly.is_public_http_url", return_value=True
            ):
                with self.assertRaises(RuntimeError):
                    queue._validate_row(dict(ROW, **updates))

    def test_verified_normal_fields_are_accepted(self):
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            got = queue._validate_row(dict(ROW))
        self.assertEqual(got["email"], ROW["email"])


class DraftHistoricalSuppressionAudit(unittest.TestCase):
    def test_suppressed_company_never_reaches_imap(self):
        with patch("myhost_draft.load_draft", return_value=ROW), \
             patch("myhost_draft.load_suppressions", return_value=[{"status": "opt_out"}], create=True) as lookup, \
             patch("myhost_draft.match_candidate", return_value={"registry_status": "opt_out"}, create=True), \
             patch("myhost_draft.connect_imap") as imap, \
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"), \
             patch("myhost_draft.save_draft", return_value="created"):
            with self.assertRaises(RuntimeError):
                draft.create_from_queue(ROW["draft_id"])
            lookup.assert_called_once()
            imap.assert_not_called()

    def test_registry_unavailable_never_reaches_imap(self):
        with patch("myhost_draft.load_draft", return_value=ROW), \
             patch("myhost_draft.load_suppressions", side_effect=RuntimeError("offline"), create=True) as lookup, \
             patch("myhost_draft.match_candidate", return_value=None, create=True), \
             patch("myhost_draft.connect_imap") as imap, \
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"), \
             patch("myhost_draft.save_draft", return_value="created"):
            with self.assertRaises(RuntimeError):
                draft.create_from_queue(ROW["draft_id"])
            lookup.assert_called_once()
            imap.assert_not_called()

    def test_clear_registry_keeps_one_draft_only(self):
        client = Mock()
        with patch("myhost_draft.load_draft", return_value=ROW), \
             patch("myhost_draft.load_suppressions", return_value=[], create=True), \
             patch("myhost_draft.match_candidate", return_value=None, create=True), \
             patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"), \
             patch("myhost_draft.save_draft", return_value="created") as store:
            self.assertEqual(draft.create_from_queue(ROW["draft_id"]), "created")
            store.assert_called_once_with(client, "Drafts", ROW)
        client.logout.assert_called_once()


if __name__ == "__main__":
    unittest.main()
