"""Offline-only regressions for the owner's single neutral mail format."""
import unittest
from unittest.mock import Mock, patch

import myhost_draft
from short_email_policy import OPT_OUT, validate_short_email


def valid_row():
    return {
        "draft_id": "draft-" + "a" * 32,
        "company": "Fictieve Zaak",
        "email": "info@voorbeeld.example",
        "source_url": "https://voorbeeld.example/contact",
        "subject": "Korte vraag over jullie afspraken",
        "body": "\n\n".join((
            "Goedendag,",
            "Ik zag dat klanten bij jullie telefonisch een afspraak kunnen maken.",
            "Zou het handig zijn als klanten ook zelf online een tijdstip kunnen kiezen?",
            OPT_OUT,
            "Groet,\nAndrew",
        )),
    }


class SingleMailPolicyTests(unittest.TestCase):
    def test_only_short_evidence_style_is_allowed(self):
        validate_short_email(valid_row())

    def test_six_branch_sales_text_no_longer_accepted_for_new_drafts(self):
        old = valid_row()
        old["body"] = ("Goedendag,\n\nIk help lokale ondernemers met AI-automatisering.\n\n"
                       "Zal ik een social voorbeeld sturen?\n\n" + OPT_OUT + "\n\nGroet,\nAndrew")
        with self.assertRaisesRegex(RuntimeError, "short_email_"):
            validate_short_email(old)

    def test_user_reported_social_example_style_is_rejected(self):
        old = valid_row()
        old["body"] = "\n\n".join((
            "Goedendag,",
            "De fictieve keuken biedt gerechten en een bestaande reserveringsoptie.",
            "Ik kan één social voorbeeld rond het menu schetsen.",
            "Zal ik het menu als voorbeeld nemen?",
            OPT_OUT,
            "Groet,\nAndrew",
        ))
        with self.assertRaisesRegex(RuntimeError, "short_email_"):
            validate_short_email(old)

    def test_no_missing_optout_extra_pitch_or_changed_greeting(self):
        for change in (
            lambda s: s.replace(OPT_OUT, ""),
            lambda s: s.replace("Goedendag,", "Hoi,"),
            lambda s: s.replace("Groet,\nAndrew", "Met vriendelijke groet,\nAndrew"),
            lambda s: s.replace("Ik zag dat ", "Ik kan "),
            lambda s: s.replace("Zou het handig zijn als ", "Wat vinden jullie als "),
            lambda s: s.replace("tijdstip kunnen kiezen?", "tijdstip kunnen kiezen? Echt?"),
            lambda s: s.replace("\n\nZou", "\n\nIk help bedrijven.\n\nZou"),
        ):
            with self.subTest(change=str(change)):
                row = valid_row()
                row["body"] = change(row["body"])
                with self.assertRaises(RuntimeError):
                    validate_short_email(row)

    def test_commercial_subject_is_rejected(self):
        row = valid_row()
        row["subject"] = "Gratis aanbieding voor meer omzet"
        with self.assertRaisesRegex(RuntimeError, "short_email_subject_invalid"):
            validate_short_email(row)

    def test_single_old_template_never_reaches_imap(self):
        row = valid_row()
        row["body"] = "Goedendag,\n\nIk help jullie graag.\n\nGroet,\nAndrew"
        with patch("myhost_draft.load_draft", return_value=row), \
             patch("myhost_draft.load_suppressions") as reg, \
             patch("myhost_draft.connect_imap") as imap:
            with self.assertRaisesRegex(RuntimeError, "short_email_"):
                myhost_draft.create_from_queue(row["draft_id"])
        reg.assert_not_called()
        imap.assert_not_called()

    def test_batch_skips_obsolete_copy_but_preserves_suppressions(self):
        approved = valid_row()
        obsolete = dict(approved)
        obsolete["draft_id"] = "draft-" + "b" * 32
        obsolete["email"] = "info@tweede.example"
        obsolete["company"] = "Tweede Fictieve Zaak"
        obsolete["source_url"] = "https://tweede.example/contact"
        obsolete["body"] = "Goedendag,\n\nDit is oude verkooptekst."
        client = Mock()
        with patch("myhost_draft.load_drafts", return_value=[approved, obsolete]), \
             patch("myhost_draft.load_suppressions", return_value=[]) as reg, \
             patch("myhost_draft.match_candidate", return_value=None), \
             patch("myhost_draft.connect_imap", return_value=client), \
             patch("myhost_draft.find_drafts_folder", return_value="Drafts"), \
             patch("myhost_draft.save_draft", return_value="created") as saved:
            result = myhost_draft.create_batch_from_queue(
                [approved["draft_id"], obsolete["draft_id"]])
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped_invalid"], 1)
        reg.assert_called_once()
        saved.assert_called_once()
        self.assertEqual(saved.call_args.args[2]["draft_id"], approved["draft_id"])


if __name__ == "__main__":
    unittest.main()
