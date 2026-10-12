"""Synthetic regression tests for one-time aggregate historical mail recheck."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from historical_v2 import token, row_for_match
import _once_historical_mail_checks as audit


class HistoricalMailCheckTests(unittest.TestCase):
    def setUp(self):
        self.key = b"synthetic-only-not-production"
        self.guard = row_for_match({
            "emails": {token(self.key, "email", f"info{i}@bedrijf.nl") for i in range(1128)},
            "official": set(), "corporate": set(),
        }, self.key)

    def one(self, n, payload=None):
        return {
            "email": f"info{n}@bedrijf.nl",
            "payload": payload or {},
            "status": 1,
        }

    def test_previously_suppressed_never_generates_new_drafts(self):
        c = audit.check_one(self.one(1), self.guard)
        self.assertEqual(c["historical_email_excluded"], 1)
        self.assertEqual(c["no_prior_mail_copy"], 1)

    def test_bad_source_provenance_holds_even_with_content(self):
        vars = {
            "leadscanner_contact_basis": "review_required",
            "leadscanner_site_refresh_subject": "oud idee",
            "leadscanner_site_refresh_body": "Hoi, ik zag een knop?",
            "leadscanner_site_refresh_observation": "Op uw site staat een knop.",
            "leadscanner_site_refresh_value_action": "Een duidelijker knop voorstellen.",
            "leadscanner_site_refresh_evidence_url": "https://other.nl/evidence",
            "leadscanner_site_refresh_contact_url": "https://bedrijf.nl/contact",
            "leadscanner_site_refresh_official_domain": "bedrijf.nl",
            "leadscanner_site_refresh_source_type": "official_site",
            "leadscanner_site_refresh_signal_type": "contact",
        }
        c = audit.check_one(self.one(2, vars), self.guard)
        self.assertEqual(c["first_party_metadata_hold"], 1)
        self.assertEqual(c["new_validator_pass"], 0)

    def test_current_quality_checks_do_not_accept_short_fake_claims(self):
        vars = {
            "leadscanner_contact_basis": "review_required",
            "leadscanner_site_refresh_subject": "RE: GRATIS! Succes gegarandeerd",
            "leadscanner_site_refresh_body": "Bel mij direct voor gegarandeerd ROI!",
            "leadscanner_site_refresh_observation": "Op onze pagina kunt u een afspraak boeken.",
            "leadscanner_site_refresh_value_action": "een duidelijkere afspraakroute",
            "leadscanner_site_refresh_evidence_url": "https://bedrijf.nl/diensten",
            "leadscanner_site_refresh_contact_url": "https://bedrijf.nl/contact",
            "leadscanner_site_refresh_official_domain": "bedrijf.nl",
            "leadscanner_site_refresh_source_type": "official_site",
            "leadscanner_site_refresh_signal_type": "appointment",
        }
        c = audit.check_one(self.one(3, vars), self.guard)
        self.assertEqual(c["new_validator_hold"], 1)
        self.assertEqual(c["new_validator_pass"], 0)

    def test_partial_final_batch_is_28_and_still_suppressed(self):
        import _once_historical_mail_checks as task
        all_rows = [self.one(i) for i in range(1128)]
        with patch.object(task, "source_rows", return_value=all_rows), \
             patch.object(task, "fetch_registry", return_value=[self.guard]):
            result = task.run(1100)
        self.assertEqual(result["offset"], 1100)
        self.assertEqual(result["size"], 28)
        self.assertEqual(result["counts"]["historical_email_excluded"], 28)
        self.assertEqual(result["drafts_created"], 0)
        self.assertEqual(result["emails_sent"], 0)

    def test_bad_offset_and_unknown_suppression_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "offset_out_of_bounds"):
            audit.run(20)
        with self.assertRaisesRegex(RuntimeError, "missing_history_suppression"):
            audit.check_one(self.one(5), row_for_match(
                {"emails": set(), "official": set(), "corporate": set()}, self.key
            ))

    def test_private_provider_error_cannot_be_printed(self):
        stream = io.StringIO()
        with patch("sys.argv", ["recheck.py", "--offset", "0"]), \
             patch.object(audit, "run", side_effect=RuntimeError("info@private.nl")), \
             redirect_stdout(stream):
            code = audit.main()
        self.assertEqual(code, 1)
        self.assertIn("details_suppressed", stream.getvalue())
        self.assertNotIn("info@private.nl", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
