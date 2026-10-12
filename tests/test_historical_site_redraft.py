"""Synthetic tests: no real contacts, site requests or mailbox writes."""
import unittest
from unittest.mock import Mock, patch

from historical_v2 import row_for_match, token
from _once_historical_site_redraft import (
    BATCH_SIZE, EXPECTED, build_batch, excluded_history, historical_site,
    run,
)


def source():
    return [{
        "id": f"00000000-0000-4000-8000-{i:012d}",
        "list_id": "24deb187-59e0-43b5-86b8-fe37a7b21e2a",
        "email": f"person{i}@company{i}.nl",
        "company_name": f"Company {i}",
        "website": None,
        "status": 1,
        "payload": {},
    } for i in range(EXPECTED)]


def suppression(rows):
    key = b"private-test-key-not-used-in-production"
    parsed = {
        "emails": {token(key, "email", x["email"]) for x in rows},
        "official": set(), "corporate": set(),
    }
    return row_for_match(parsed, key)


def finding(sentence, path):
    return {
        "text": sentence, "source_url": "https://sample.nl/" + path,
        "source_type": "official_site", "page_type": "detail",
    }


class HistoricalSiteRebuildTests(unittest.TestCase):
    def test_source_site_must_be_official_and_contact_is_not_inferred(self):
        self.assertFalse(historical_site({
            "company_domain": "gmail.com", "payload": {}, "website": "",
        }))
        self.assertEqual(historical_site({
            "website": "https://sample.nl/", "payload": {},
        }), "https://sample.nl/")
        self.assertEqual(historical_site({
            "website": "",
            "payload": {
                "leadscanner_site_refresh_source_type": "official_site",
                "leadscanner_site_refresh_evidence_url": "https://sample.nl/afspraak",
                "leadscanner_site_refresh_official_domain": "sample.nl",
            },
        }), "https://sample.nl/")

    def test_prior_replies_sends_bounce_and_unsubscribes_excluded(self):
        self.assertTrue(excluded_history({"status": -2}))
        self.assertTrue(excluded_history({"status": -1}))
        self.assertTrue(excluded_history({"status": 3}))
        self.assertTrue(excluded_history({"status": 1, "email_reply_count": 1}))
        self.assertTrue(excluded_history({"status": 1, "timestamp_last_contact": "2026-01-01"}))
        self.assertFalse(excluded_history({"status": 1, "email_reply_count": 0}))

    def test_final_batch_exactly_28_all_holds_missing_current_website(self):
        rows = source()
        verify = Mock(side_effect=AssertionError("should not request websites"))
        research = Mock(side_effect=AssertionError("should not request websites"))
        report, batch = build_batch(
            offset=1100, rows=rows, history=suppression(rows),
            verifier=verify, researcher=research,
        )
        self.assertEqual(report["size"], 28)
        self.assertEqual(report["counts"]["checked"], 28)
        self.assertEqual(report["counts"]["historical_email_excluded"], 28)
        self.assertEqual(report["counts"]["hold_missing_website"], 28)
        self.assertEqual(report["counts"]["ready_for_review"], 0)
        self.assertEqual(batch["rows"], [])
        self.assertNotIn("person1100@company1100.nl", str(report))
        verify.assert_not_called()
        research.assert_not_called()

    def test_four_independent_site_findings_and_fresh_contact_create_review_only(self):
        rows = source()
        rows[0]["website"] = "https://sample.nl/"
        verifier = Mock()
        researcher = Mock()
        def check_verify(payload, **kwargs):
            self.assertEqual(kwargs["limit"], 1)
            verified = dict(payload["candidates"][0])
            verified.update({
                "ready_for_research": True,
                "official_domain": "sample.nl",
                "official_url": "https://sample.nl/",
            })
            return {"candidates": [verified]}
        def check_research(payload, **kwargs):
            self.assertEqual(kwargs["limit"], 1)
            verified = dict(payload["candidates"][0])
            verified.update({
                "research_status": "ready", "contact_status": "verified_official_site",
                "public_business_email": "info@sample.nl",
                "email_source_url": "https://sample.nl/contact",
                "research_pages_fetched": 6,
                "evidence_candidates": [
                    finding("Klanten kunnen online een afspraak aanvragen voor de jaarlijkse onderhoudsbeurt.", "afspraak"),
                    finding("Vraag online een offerte aan via ons formulier voor maatwerk.", "offerte"),
                    finding("Bestel online uw onderdelen en kies het gewenste afleveradres.", "bestellen"),
                    finding("Onze klanten vinden antwoorden in de kennisbank met veelgestelde vragen.", "vragen"),
                ],
            })
            return {"candidates": [verified]}
        verifier.side_effect = check_verify
        researcher.side_effect = check_research
        report, batch = build_batch(
            offset=0, rows=rows, history=suppression(rows),
            verifier=verifier, researcher=researcher,
        )
        self.assertEqual(report["counts"]["checked"], BATCH_SIZE)
        self.assertEqual(report["counts"]["ready_for_review"], 1)
        self.assertEqual(report["counts"]["hold_missing_website"], 99)
        self.assertEqual(report["counts"]["websites_with_four_to_six_findings"], 1)
        self.assertEqual(report["counts"]["mail_quality_evaluated"], 1)
        self.assertEqual(len(batch["rows"]), 1)
        mail = batch["rows"][0]
        self.assertEqual(len(mail["selected_findings"]), 4)
        for item in mail["selected_findings"]:
            from outreach_stages import finding_excerpt
            self.assertIn(finding_excerpt(item), mail["body"])
        self.assertEqual(mail["body"].count("?"), 1)
        self.assertTrue(mail["lead_id"].startswith("growth-"))
        self.assertFalse(mail["automatic_send"])

    def test_unknown_suppression_fails_entire_batch(self):
        rows = source()
        wrong = suppression(rows[1:])
        with self.assertRaisesRegex(RuntimeError, "historical_suppression_incomplete"):
            build_batch(offset=0, rows=rows, history=wrong)

    def test_audit_mode_never_calls_mailbox_or_sends(self):
        rows = source()
        state = suppression(rows)
        with patch("_once_historical_site_redraft.read_source", return_value=(rows, 13)), \
             patch("_once_historical_site_redraft.fetch_registry", return_value=[state]), \
             patch("_once_historical_site_redraft.build_batch", return_value=(
                 {"counts": {"checked": 100}, "size": 100}, {"rows": []}
             )):
            result = run(0, "audit")
        self.assertEqual(result["mode"], "audit")
        self.assertEqual(result["drafts_created"], 0)
        self.assertEqual(result["drafts_exact_existing"], 0)

if __name__ == "__main__":
    unittest.main()
