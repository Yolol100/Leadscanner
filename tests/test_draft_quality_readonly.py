"""No user mail data or mailbox mutations in quality audit regressions."""
import pathlib
import unittest
from email.message import EmailMessage
from unittest.mock import patch

import draft_quality_readonly as qa


def generated_body(count=3):
    points = "\n".join(
        f"{i}. Onderdeel {i}: Verifieerbaar websiteonderdeel.\n   Verbeteridee: maak stap {i} duidelijker."
        for i in range(1, count + 1)
    )
    return (
        "Beste,\n\nIk heb jullie website bekeken en geanalyseerd.\n\n"
        + points
        + "\n\nAls je geen interesse hebt, hoef je niet te reageren.\n\n"
        + "Met vriendelijke groeten,\nAndrew"
    )


class DraftQualityAuditTests(unittest.TestCase):
    def test_three_to_six_have_only_structural_pass(self):
        for n in range(3, 7):
            with self.subTest(n=n):
                self.assertEqual(
                    qa.classify_copy(f"{n} verbeterideeën voor jullie website",
                                     generated_body(n)),
                    "structure_only_needs_source_and_human_review",
                )

    def test_one_point_and_page_heading_are_flagged(self):
        self.assertEqual(
            qa.classify_copy("idee voor reserveren",
                             "Hoi,\n\nOp jullie website viel me dit detail op: "
                             "Reserveren - Pampalini Utrecht - Lunchroom\n\n"
                             "Zal ik een voorbeeld sturen?"),
            "generic_page_title_or_copy",
        )
        self.assertEqual(qa.classify_copy("idee", "Hoi, iets over jullie site."),
                         "legacy_single_or_two_points")

    def test_two_points_are_never_ready(self):
        self.assertEqual(
            qa.classify_copy("2 verbeterideeën", generated_body(2)),
            "legacy_single_or_two_points",
        )

    def test_missing_fixes_or_reply_option_is_flagged(self):
        body = generated_body(3)
        self.assertEqual(qa.classify_copy("3 tips", body.replace("Verbeteridee:", "Idee:")),
                         "practical_fixes_missing")
        self.assertEqual(
            qa.classify_copy("3 tips", body.replace(
                "Als je geen interesse hebt, hoef je niet te reageren.", "")),
            "optout_or_signature_missing",
        )

    def test_nonsequential_and_subject_mismatch_are_flagged(self):
        body = generated_body(3)
        self.assertEqual(qa.classify_copy("3 tips", body.replace("2. Onderdeel", "4. Onderdeel")),
                         "points_not_sequential")
        self.assertEqual(qa.classify_copy("4 tips", body),
                         "subject_count_mismatch")

    def test_private_output_is_50_at_a_time_and_no_identity(self):
        batch = [("oude titel", "Hoi, geen verbeterpunten.") for _ in range(509)]
        report = qa.batch_summaries(batch)
        self.assertEqual(report["checked"], 509)
        self.assertEqual([b["checked"] for b in report["batches"]],
                         [50] * 10 + [9])
        self.assertEqual(report["counts"]["legacy_single_or_two_points"], 509)
        self.assertEqual(sum(report["counts"].values()), 509)
        self.assertNotIn("Hoi", str(report))
        self.assertFalse(report["mailbox_writes"])
        self.assertFalse(report["send_approved"])
        with self.assertRaises(ValueError):
            qa.batch_summaries(batch, size=100)

    def test_imap_fetch_peek_and_readonly_only(self):
        original = EmailMessage()
        original["Subject"] = "3 verbeterideeën"
        original["X-Leadscanner-Lead-ID"] = "growth-" + "a" * 20
        original.set_content(generated_body(3))
        class FakeIMAP:
            def __init__(self):
                self.ops = []
            def fetch(self, seq, args):
                self.ops.append(("fetch", seq, args))
                return "OK", [(b"1 (BODY[] {300})", original.as_bytes())]
        fake = FakeIMAP()
        with patch("myhost_draft.select_folder") as select, \
             patch("myhost_draft.find_message_ids", return_value=[b"1"]), \
             patch("myhost_draft.lead_id_from_message", return_value="growth-" + "a" * 20):
            subject, body = qa.fetch_existing_copy(fake, "Drafts", "growth-" + "a" * 20)
            select.assert_called_once_with(fake, "Drafts", readonly=True)
        self.assertEqual(subject, "3 verbeterideeën")
        self.assertIn("Verbeteridee", body)
        self.assertEqual(fake.ops, [("fetch", b"1", "(BODY.PEEK[])")])

    def test_source_cannot_send_or_mutate_mail(self):
        src = (pathlib.Path(__file__).resolve().parents[1] /
               "scripts/draft_quality_readonly.py").read_text()
        for forbidden in ('uid_expunge_only(', 'client.uid("copy"', 'client.append(',
                          'client.store(', 'send_message(', 'sendmail(', 'create_drafts('):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
