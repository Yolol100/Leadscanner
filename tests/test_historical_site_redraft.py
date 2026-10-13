"""Synthetic tests: no real contacts, site requests or mailbox writes."""
import unittest
from unittest.mock import Mock, patch

from historical_v2 import row_for_match, token
from _once_historical_site_redraft import (
    BATCH_SIZE, EXPECTED, build_batch, excluded_history, historical_site,
    historical_registry_hold, historical_brand_hint, require_fresh_registry_before_imap, run,
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
        }), "https://sample.nl")

    def test_source_hints_do_not_perform_dns_and_reject_local_or_credentialed_urls(self):
        site_row = {"company_name": None, "website": "https://made-up-site.nl/"}
        with patch("socket.getaddrinfo", side_effect=AssertionError("source loop must not do DNS")):
            self.assertEqual(historical_site(site_row), "https://made-up-site.nl/")
        for unsafe in (
            "http://127.0.0.1/", "https://10.10.1.1/", "http://localhost/",
            "https://admin:secret@business.nl", "http://server.local/path",
            "https://business.nl:8080/",
        ):
            self.assertEqual(
                historical_site({"website": unsafe}), "",
                msg="unsafe source URL must fail before live website crawl",
            )

    def test_missing_company_name_can_use_only_correlated_domain_for_research(self):
        row = {
            "company_name": None, "website": "https://sample.nl/",
            "email": "info@sample.nl", "company_domain": "sample.nl",
            "payload": {},
        }
        self.assertFalse(historical_brand_hint(row, "https://sample.nl/"))
        key = b"test-only-key"
        corporate_history = {
            "v2_key": key,
            "v2_corporate": {token(key, "corporate", "sample.nl")},
        }
        self.assertEqual(
            historical_brand_hint(row, "https://sample.nl/", corporate_history), "sample"
        )
        row["email"] = "info@gmail.com"
        row["company_domain"] = "gmail.com"
        self.assertFalse(historical_brand_hint(row, "https://sample.nl/"))
        row["payload"] = {
            "leadscanner_site_refresh_source_type": "official_site",
            "leadscanner_site_refresh_official_domain": "sample.nl",
            "leadscanner_site_refresh_evidence_url": "https://sample.nl/contact",
        }
        self.assertEqual(historical_brand_hint(row, "https://sample.nl/"), "sample")
        # A shared provider must not acquire authority from its own domain.
        row["payload"] = {}
        row["email"] = "info@bigmailprovider.xyz"
        row["company_domain"] = "bigmailprovider.xyz"
        self.assertFalse(historical_brand_hint(row, "https://bigmailprovider.xyz"))

    def test_derived_domain_brand_without_live_text_proof_is_held(self):
        rows = source()
        rows[0]["company_name"] = None
        rows[0]["website"] = "https://sample.nl/"
        rows[0]["company_domain"] = "sample.nl"
        rows[0]["payload"] = {
            "leadscanner_site_refresh_source_type": "official_site",
            "leadscanner_site_refresh_official_domain": "sample.nl",
            "leadscanner_site_refresh_evidence_url": "https://sample.nl/contact",
        }
        def verifier(data, **kwargs):
            verified = dict(data["candidates"][0])
            verified.update({
                "ready_for_research": True, "official_domain": "sample.nl",
                "identity_evidence": ["brand_token_in_domain:sample"],
            })
            return {"candidates": [verified]}
        no_research = Mock(side_effect=AssertionError("domain-only identity not enough"))
        report, batch = build_batch(
            offset=0, rows=rows, history=suppression(rows),
            verifier=verifier, researcher=no_research,
        )
        self.assertEqual(report["counts"]["hold_website_verification"], 1)
        self.assertEqual(report["counts"]["hold_missing_website"], 99)
        no_research.assert_not_called()
        self.assertEqual(batch["rows"], [])

    def test_prior_replies_sends_bounce_and_unsubscribes_excluded(self):
        self.assertTrue(excluded_history({"status": -2}))
        self.assertTrue(excluded_history({"status": -1}))
        self.assertTrue(excluded_history({"status": 3}))
        self.assertTrue(excluded_history({"status": 1, "email_reply_count": 1}))
        self.assertTrue(excluded_history({"status": 1, "timestamp_last_contact": "2026-01-01"}))
        self.assertTrue(excluded_history({"status": 1, "email_open_count": 1}))
        self.assertTrue(excluded_history({"status": 1, "email_click_count": 1}))
        self.assertTrue(excluded_history({"status": 1, "timestamp_last_open": "2026-01-01"}))
        self.assertTrue(excluded_history({"status": 1, "timestamp_last_click": "2026-01-01"}))
        self.assertTrue(excluded_history({"status": 1, "email_replied_step": 0}))
        self.assertTrue(excluded_history({"status": 1, "lt_interest_status": 1}))
        self.assertTrue(excluded_history({"status": 1, "lt_interest_status": -3}))
        self.assertTrue(excluded_history({"status": 1, "status_summary_subseq": {
            "timestampExecuted": "2026-01-01"
        }}))
        self.assertFalse(excluded_history({
            "status": 1, "email_reply_count": 0,
            "email_opened_step": None, "lt_interest_status": 0,
        }))

    def test_website_without_independent_company_provenance_is_separate_hold(self):
        rows = source()
        rows[0]["website"] = "https://unrelated-site.nl/"
        rows[0]["company_name"] = None
        rows[0]["company_domain"] = "company0.nl"
        no_fetch = Mock(side_effect=AssertionError("no live fetch for weak source link"))
        report, batch = build_batch(
            offset=0, rows=rows, history=suppression(rows),
            verifier=no_fetch, researcher=no_fetch,
        )
        self.assertEqual(report["counts"]["hold_missing_business_identity"], 1)
        self.assertEqual(report["counts"]["hold_missing_website"], 99)
        no_fetch.assert_not_called()
        self.assertEqual(batch["rows"], [])

    def test_original_registry_blocks_optouts_sends_but_allows_historical_concept_review(self):
        from dedupe_preflight import candidate_identity
        address = "person0@company0.nl"
        item = {"identity": candidate_identity({"email": address}),
                "status": "opt_out", "row_number": 2}
        self.assertTrue(historical_registry_hold({"email": address}, [item], original_email=address))
        item["status"] = "sent"
        self.assertTrue(historical_registry_hold({"email": address}, [item], original_email=address))
        item["status"] = "concept"
        self.assertFalse(historical_registry_hold({"email": address}, [item], original_email=address))
        second = {"identity": candidate_identity({"email": address}),
                  "status": "unsubscribed", "row_number": 3}
        self.assertTrue(historical_registry_hold(
            {"email": address}, [item, second], original_email=address
        ))
        self.assertTrue(historical_registry_hold({"email": "new@company0.nl"},
                                                 [item], original_email="old@company0.nl")
                        is False)  # nonmatching email cannot be inferred

    def test_registry_optout_is_excluded_before_any_site_visit(self):
        from dedupe_preflight import candidate_identity
        rows = source()
        rows[0]["website"] = "https://sample.nl/"
        registry = [{"identity": candidate_identity({"email": rows[0]["email"]}),
                     "status": "opt_out", "row_number": 2}]
        site_call = Mock(side_effect=AssertionError("must never visit blocked website"))
        result, batch = build_batch(
            offset=0, rows=rows, history=suppression(rows),
            ordinary=registry, verifier=site_call, researcher=site_call,
        )
        self.assertEqual(result["counts"]["excluded_history"], 1)
        self.assertEqual(result["counts"]["hold_missing_website"], 99)
        site_call.assert_not_called()
        self.assertEqual(batch["rows"], [])

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
                "site_issue_candidates": [
                    {"category": name, "source_type": "official_site",
                     "source_url": "https://sample.nl/contact",
                     "severity": rank, "observation_nl": observation}
                    for name, rank, observation in (
                        ("broken_internal_link", 100, "Een interne link op de website geeft bij twee controles een status HTTP 404"),
                        ("unlabeled_form_control", 90, "Een invoerveld in het formulier heeft geen correct gekoppeld toegankelijk label"),
                        ("unnamed_image_link", 85, "Een afbeeldingslink in de HTML heeft geen tekstalternatief of toegankelijke naam"),
                    )
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
        self.assertEqual(report["counts"]["websites_with_two_to_three_findings"], 1)
        self.assertEqual(report["counts"]["mail_quality_evaluated"], 1)
        self.assertEqual(len(batch["rows"]), 1)
        mail = batch["rows"][0]
        self.assertEqual(len(mail["selected_findings"]), 3)
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

    def test_last_second_opt_out_stops_imap_before_any_write(self):
        from dedupe_preflight import candidate_identity
        source_rows = source()
        hist = suppression(source_rows)
        source_hash = token(hist["v2_key"], "email", source_rows[0]["email"])
        row = {
            "status": "review_draft", "automatic_send": False,
            "_historical_source_email_token": source_hash,
            "email": source_rows[0]["email"],
            "website": "https://sample.nl/", "official_domain": "sample.nl",
            "company": "Sample",
        }
        ordinary = {
            "identity": candidate_identity({"email": row["email"]}),
            "status": "opt_out", "row_number": 2,
        }
        with self.assertRaisesRegex(RuntimeError, "fresh_registry_existing_exclusion"):
            require_fresh_registry_before_imap({"rows": [row]}, hist, [hist, ordinary])
        ordinary["status"] = "concept"
        require_fresh_registry_before_imap({"rows": [row]}, hist, [hist, ordinary])
        ordinary["status"] = "sent"
        with self.assertRaisesRegex(RuntimeError, "fresh_registry_existing_exclusion"):
            require_fresh_registry_before_imap({"rows": [row]}, hist, [hist, ordinary])

    def test_changed_key_or_another_historical_mailbox_is_rejected(self):
        rows = source()
        hist = suppression(rows)
        source_hash = token(hist["v2_key"], "email", rows[0]["email"])
        next_hash = token(hist["v2_key"], "email", rows[1]["email"])
        batch = {"rows": [{
            "status": "review_draft", "automatic_send": False,
            "_historical_source_email_token": source_hash,
            "email": rows[1]["email"], "official_domain": "sample.nl",
            "company": "Sample", "website": "https://sample.nl/",
        }]}
        self.assertIn(next_hash, hist["v2_emails"])
        with self.assertRaisesRegex(RuntimeError, "fresh_other_historical_recipient"):
            require_fresh_registry_before_imap(batch, hist, [hist])
        other = dict(hist, v2_key=b"different-key")
        with self.assertRaisesRegex(RuntimeError, "fresh_historical_registry_changed"):
            require_fresh_registry_before_imap(batch, hist, [other])

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
