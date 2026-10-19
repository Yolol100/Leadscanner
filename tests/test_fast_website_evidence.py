"""No-network tests for private fast website evidence and exact-email HTTP shortcut."""
import json
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import fast_website_evidence as q
from verify_official_lead import verify_official_site
from test_verified_fill_100 import FakeResponse


def record():
    return {
        "record_key": "Approved:synthetic", "source_tab": "Approved",
        "source_row": "2", "source_sha256": "abc", "company": "Hovenier Amstel",
        "website": "https://voorbeeld.nl/", "email": "info@voorbeeld.nl",
        "branch": "hoveniers"
    }


def verified(**changes):
    result = dict(record(), email_source_url="https://voorbeeld.nl/contact",
                  facts_json="[]", feature_mentions_json="[]",
                  checked_at=datetime.now(timezone.utc).isoformat(),
                  status="verified_with_detail", reason="confirmed")
    result.update(changes)
    return result


class OwnerEvidenceCommandContractTests(unittest.TestCase):
    def test_exact_authorization_and_shared_imap_source_lock(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1]
                    / ".github/workflows/fast-website-evidence.yml").read_text()
        self.assertIn("issue_comment:", workflow)
        self.assertIn("github.event.issue.number == 1659", workflow)
        self.assertIn("github.actor == 'Yolol100'", workflow)
        self.assertIn("github.event.comment.user.login == 'Yolol100'", workflow)
        self.assertIn("!github.event.issue.pull_request", workflow)
        self.assertIn("group: leadscanner-myhost-draft", workflow)
        self.assertIn("queue: max", workflow)
        for i in range(1, 6):
            self.assertIn("LEADS_EVIDENCE_V1:REVIEW450_BATCH_" + str(i),
                          workflow)
        self.assertIn("SOURCE=Review450", workflow)
        self.assertIn('python3 scripts/fast_website_evidence.py --source "$SOURCE" --batch "$BATCH"', workflow)
        self.assertNotIn("cron:", workflow)
        self.assertNotIn("smtplib", workflow)


    def test_noop_events_do_not_hold_owner_recheck_queue(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1]
                    / ".github/workflows/fast-website-evidence.yml").read_text()
        # Actual source writes retain both independent serialization gates.
        self.assertIn("'leads-private-candidates'", workflow)
        self.assertIn("group: leadscanner-myhost-draft", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("queue: max", workflow)
        # Unrelated issue comments and PR tests do not block owner rechecks.
        self.assertIn("leads-evidence-skip-{0}", workflow)
        self.assertIn("github.run_id", workflow)
        self.assertIn("github.event_name == 'issue_comment'", workflow)
        self.assertIn("github.event.comment.body", workflow)
        self.assertNotIn("github.event_name == 'push'", workflow)
        self.assertNotIn("LEADS_EVIDENCE_ONCE:", workflow)
        self.assertNotIn("LEADS_CACHE_SMOKE:", workflow)

class FastOfficialEvidenceTests(unittest.TestCase):
    def test_private_failure_class_is_anonymous_and_does_not_approve(self):
        entry = record()

        def denied(hint, **kwargs):
            self.assertEqual(hint["name_hint"], entry["company"])
            kwargs["diagnostic"]("robots_unavailable")
            return None

        with patch.object(q, "verify_official_site", side_effect=denied):
            outcome = q.inspect(entry)
        self.assertEqual(outcome["status"], "needs_manual_check")
        self.assertEqual(outcome["reason"], "official_robots_unavailable")
        # Identity fields intentionally remain in the PRIVATE record. The
        # added diagnostic must never copy them into a public reason code.
        self.assertNotIn(entry["email"], outcome["reason"])
        self.assertNotIn(entry["company"], outcome["reason"])

    def test_unclassified_verifier_errors_still_reject_without_leaking(self):
        with patch.object(q, "verify_official_site",
                          side_effect=ValueError("private contact detail")):
            outcome = q.inspect(record())
        self.assertEqual(outcome["status"], "needs_manual_check")
        self.assertEqual(outcome["reason"], "bounded_official_site_request_failed")
        self.assertNotIn("private contact detail", json.dumps(outcome))

    def test_only_exact_email_shortcut_skips_contact_page(self):
        hint = {"name_hint": "Schildersbedrijf Amstel",
                "website_hint": "https://voorbeeld.nl/",
                "category_hint": "painter"}
        page = ('<h1>Schildersbedrijf Amstel</h1>'
                '<p>Amstel is een schildersbedrijf.</p>'
                '<a href="/contact">Contact</a>'
                '<a href="mailto:info@voorbeeld.nl">info@voorbeeld.nl</a>')
        client = Mock()
        client.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt") else FakeResponse(page))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            result = verify_official_site(hint, session=client,
                                          expected_email="info@voorbeeld.nl")
        self.assertEqual(result["email"], "info@voorbeeld.nl")
        self.assertEqual(client.get.call_count, 2)  # robots + official homepage
        self.assertEqual(result["source_url"], "https://voorbeeld.nl/")

    def test_default_verification_still_checks_contact_page(self):
        hint = {"name_hint": "Schildersbedrijf Amstel",
                "website_hint": "https://voorbeeld.nl/",
                "category_hint": "painter"}
        page = ('<h1>Schildersbedrijf Amstel</h1>'
                '<p>Amstel is een schildersbedrijf.</p>'
                '<a href="/contact">Contact</a>'
                '<a href="mailto:info@voorbeeld.nl">info@voorbeeld.nl</a>')
        client = Mock()
        client.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt") else FakeResponse(page))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            result = verify_official_site(hint, session=client)
        self.assertEqual(result["email"], "info@voorbeeld.nl")
        self.assertEqual(client.get.call_count, 3)

    def test_contact_link_takes_priority_over_about_with_same_request_cap(self):
        """A preceding about link must not hide the published contact email."""
        hint = {"name_hint": "Schildersbedrijf Amstel",
                "website_hint": "https://voorbeeld.nl/",
                "category_hint": "painter"}
        home = ('<h1>Schildersbedrijf Amstel</h1>'
                '<p>Amstel doet schilderswerk in 5211 AB.</p>'
                '<a href="/over-ons">Over ons</a>'
                '<a href="/contact/">Contact</a>')
        about = '<p>Wij zijn Schildersbedrijf Amstel.</p>'
        contact = ('<p>Schildersbedrijf Amstel 5211 AB, schilderwerken.</p>'
                   '<a href="mailto:info@voorbeeld.nl">Mail ons</a>'
                   '<p>info@voorbeeld.nl</p>')
        client = Mock()
        urls = []

        def fetch(url, **kwargs):
            urls.append(url)
            if url.endswith("robots.txt"):
                return FakeResponse(status=404)
            if url.endswith("/over-ons"):
                return FakeResponse(about)
            if url.endswith("/contact/"):
                return FakeResponse(contact)
            return FakeResponse(home)

        client.get.side_effect = fetch
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            result = verify_official_site(
                hint, session=client, expected_email="info@voorbeeld.nl",
                collect_evidence=True)
        self.assertEqual(result["email"], "info@voorbeeld.nl")
        self.assertEqual(result["source_url"], "https://voorbeeld.nl/contact/")
        self.assertEqual(len(result["_captured_pages"]), 2)
        self.assertEqual(client.get.call_count, 3)
        self.assertFalse(any(url.endswith("/over-ons") for url in urls))

    def test_exact_unpublished_address_never_replaced_by_other_email(self):
        hint = {"name_hint": "Schildersbedrijf Amstel",
                "website_hint": "https://voorbeeld.nl/",
                "category_hint": "painter"}
        page = ('<h1>Schildersbedrijf Amstel</h1>'
                '<p>Schilderwerken Amstel</p>'
                '<a href="mailto:info@voorbeeld.nl">info@voorbeeld.nl</a>')
        client = Mock()
        client.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt") else FakeResponse(page))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            self.assertIsNone(verify_official_site(
                hint, session=client, expected_email="info@anders.nl"))

    def test_disputed_activity_is_never_implied(self):
        self.assertFalse(q._has("Wij serveren geen veganistische gerechten", "veganistische"))
        self.assertTrue(q._has("Groepsmenu en afhaalservice", "groepsmenu"))

    def test_accented_activity_does_not_lose_its_quote(self):
        record_data = dict(record(), branch="horecazaken")
        official = {"email": record_data["email"],
                    "branche_meervoud": "horecazaken",
                    "source_url": record_data["website"]}
        pages = [(record_data["website"],
                  "Welkom bij ons speciaalbier caf\u00e9 in 5211 AB. "
                  "Voorbeeld ontvangt gasten en serveert speciaalbier.")]
        out = q.inspect_verified(record_data, official, pages)
        self.assertEqual(out["status"], "verified_activity_only")
        self.assertEqual(out["reason"],
                         "official_email_and_local_activity_confirmed")
        self.assertIn("caf\u00e9", q._excerpt(pages[0][1], "cafe"))

    def test_accented_negation_still_skips_denied_service(self):
        text = ("Wij bieden geen caf\u00e9. "
                "Meer details komen later beschikbaar. "
                "Bij onze tweede vestiging is een caf\u00e9ruimte geopend.")
        quote = q._excerpt(text, "cafe")
        self.assertIn("caf\u00e9ruimte", quote)
        self.assertNotIn("geen caf\u00e9", quote)
        self.assertEqual(q._excerpt("Wij bieden geen caf\u00e9.", "cafe"), "")

    def test_quote_matches_spacing_and_decomposed_unicode(self):
        self.assertIn("high tea", q._excerpt(
            "Deze zaak verzorgt high   tea op aanvraag.", "high tea"))
        self.assertIn("cafe\u0301", q._excerpt(
            "Op ons terras is een cafe\u0301 gevestigd.", "cafe"))

    def test_locality_and_cross_domain_gates_remain_closed(self):
        row = dict(record(), branch="horecazaken")
        official = {"email": row["email"],
                    "branche_meervoud": "horecazaken",
                    "source_url": row["website"]}
        result = q.inspect_verified(row, official,
            [(row["website"], "Voorbeeld heeft een caf\u00e9 in Nederland.")])
        self.assertEqual(result["reason"], "dutch_locality_not_confirmed")
        changed = dict(row, email="info@anderbedrijf.nl")
        result = q.inspect_verified(changed,
            {**official, "email": changed["email"]},
            [(row["website"], "Voorbeeld heeft een caf\u00e9 in 5211 AB.")])
        self.assertEqual(result["reason"],
                         "cross_domain_email_needs_independent_association")

    def test_quote_never_uses_negated_occurrence_when_later_supported(self):
        """The evidence quote must identify the *affirmative* match, not a denied one."""
        text = ("Wij bieden geen groepsmenu. "
                "Meer informatie staat op onze website. "
                "Ook ontvangen we aanvragen via telefoon en e-mail. "
                "Voor grotere groepen verzorgen we een groepsmenu op aanvraag.")
        found = q._mentions([("https://voorbeeld.nl/aanbod", text)], ("groepsmenu",), 1)
        self.assertEqual(len(found), 1)
        self.assertIn("groepsmenu op aanvraag", found[0]["excerpt"])
        self.assertNotIn("geen groepsmenu", found[0]["excerpt"])

    def test_previously_existing_functions_are_only_mentions(self):
        pages = [("https://voorbeeld.nl/", "Hovenier Amstel 5211 AB "
                  "tuinonderhoud en tuinontwerp, online boeken en offertevragen")]
        official = {"email": "info@voorbeeld.nl", "branche_meervoud": "hoveniers",
                    "source_url": "https://voorbeeld.nl/"}
        out = q.inspect_verified(record(), official, pages)
        self.assertEqual(out["status"], "verified_with_detail")
        signal = json.loads(out["feature_mentions_json"])[0]
        self.assertEqual(signal["certainty"], "text_mention_only")
        self.assertIn("source_url", signal)

    def test_explicit_pedicure_and_group_classes_count_as_local_activity(self):
        # Both are permitted target-industry activities, but require actual
        # direct official-site wording. Neither is inferred from a sector.
        for branch, confirmed, negated in [
            ("schoonheidssalons", "medisch pedicure", "geen pedicure"),
            ("sportscholen", "groepslessen", "geen groepslessen"),
        ]:
            with self.subTest(branch=branch):
                row = dict(record(), branch=branch)
                official = {
                    "email": row["email"], "branche_meervoud": branch,
                    "source_url": row["website"],
                }
                pages = [(row["website"],
                          "Hovenier Amstel in 5211 AB biedt " + confirmed)]
                got = q.inspect_verified(row, official, pages)
                self.assertIn(got["status"],
                              {"verified_activity_only", "verified_with_detail"})
                denied = [(row["website"],
                           "Hovenier Amstel in 5211 AB biedt " + negated)]
                blocked = q.inspect_verified(row, official, denied)
                self.assertEqual(blocked["status"], "needs_manual_check")
                self.assertEqual(blocked["reason"], "activity_not_confirmed")

    def test_concrete_hotel_cafe_and_gym_services_require_official_text(self):
        cases = [
            ("logiesbedrijven", "hotel", "familiekamer"),
            ("horecazaken", "cafe", "brunch"),
            ("sportscholen", "sportschool", "proefles"),
        ]
        for branch, activity, detail in cases:
            with self.subTest(branch=branch):
                company = "Amstel Voorbeeld"
                website = "http://voorbeeld.nl/"
                record_data = dict(record(), company=company, website=website,
                                   branch=branch)
                official = {"email": record_data["email"],
                            "branche_meervoud": branch,
                            "source_url": website + "contact"}
                source = [(website, f"{company} 5211 AB "
                           f"Wij zijn een {activity} en bieden {detail}.")]
                out = q.inspect_verified(record_data, official, source)
                self.assertEqual(out["status"], "verified_with_detail")
                self.assertIn(detail, json.loads(out["facts_json"])[0]["term"])
                unsupported = [(website, f"{company} 5211 AB "
                                f"Wij zijn een {activity}.")]
                missed = q.inspect_verified(record_data, official, unsupported)
                self.assertEqual(missed["status"], "verified_activity_only")
                self.assertEqual(missed["facts_json"], "[]")

    def test_wrong_branch_or_unconfirmed_email_fails_closed(self):
        pages = [("https://voorbeeld.nl/", "Hovenier Amstel 5211 AB tuinonderhoud")]
        self.assertEqual(q.inspect_verified(record(), None, pages)["status"], "needs_manual_check")
        result = q.inspect_verified(record(), {
            "email": "info@voorbeeld.nl", "branche_meervoud": "schilders",
            "source_url": "https://voorbeeld.nl/"}, pages)
        self.assertEqual(result["reason"], "official_identity_email_or_branch_mismatch")

    def test_cross_domain_email_requires_extra_review(self):
        r = record()
        r["email"] = "info@anderbedrijf.nl"
        pages = [("https://voorbeeld.nl/", "Hovenier Amstel 5211 AB tuinonderhoud")]
        result = q.inspect_verified(r, {
            "email": r["email"], "branche_meervoud": "hoveniers",
            "source_url": "https://voorbeeld.nl/contact"}, pages)
        self.assertEqual(result["status"], "needs_manual_check")
        self.assertEqual(result["reason"], "cross_domain_email_needs_independent_association")

    def test_officially_published_cross_domain_email_accepted_only_at_source(self):
        source = "https://voorbeeld.nl/contact"
        r = dict(record(), email="info@secondary.nl")
        official = {
            "email": r["email"], "branche_meervoud": "hoveniers",
            "source_url": source
        }
        pages = [(r["website"], "Hovenier Amstel 5211 AB tuinonderhoud"),
                 (source, "Hovenier Amstel 5211 AB tuinontwerp info@secondary.nl")]
        result = q.inspect_verified(r, official, pages)
        self.assertEqual(result["status"], "verified_with_detail")
        self.assertEqual(result["reason"],
                         "official_email_and_local_activity_confirmed")
        self.assertEqual(result["email_source_url"], source)

        no_publication = [(r["website"],
                          "Hovenier Amstel 5211 AB tuinonderhoud"),
                          (source, "Hovenier Amstel 5211 AB tuinontwerp")]
        blocked = q.inspect_verified(r, official, no_publication)
        self.assertEqual(blocked["status"], "needs_manual_check")
        self.assertEqual(blocked["reason"],
                         "cross_domain_email_needs_independent_association")

        wrong_page = [(r["website"],
                       "Hovenier Amstel 5211 AB tuinonderhoud info@secondary.nl"),
                      (source, "Hovenier Amstel 5211 AB tuinontwerp")]
        mismatch = q.inspect_verified(r, official, wrong_page)
        self.assertEqual(mismatch["status"], "needs_manual_check")

        different_domain = [(r["website"],
                             "Hovenier Amstel 5211 AB tuinonderhoud"),
                            ("https://another.example/contact",
                             "Hovenier Amstel 5211 AB info@secondary.nl")]
        unsafe = q.inspect_verified(r, official, different_domain)
        self.assertEqual(unsafe["status"], "needs_manual_check")

    def test_cross_domain_published_address_does_not_override_identity(self):
        r = dict(record(), email="info@secondary.nl")
        source = "https://voorbeeld.nl/contact"
        pages = [(r["website"], "Hovenier Amstel 5211 AB tuinonderhoud"),
                 (source, "Hovenier Amstel 5211 AB info@secondary.nl")]
        other = q.inspect_verified(r, {
            "email": "info@wrong.nl", "branche_meervoud": "hoveniers",
            "source_url": source}, pages)
        self.assertEqual(other["status"], "needs_manual_check")
        self.assertEqual(other["reason"], "official_identity_email_or_branch_mismatch")

    def test_cross_domain_exact_official_page_publication_is_accepted(self):
        """Never reject an exact business address on the validated official page."""
        r = dict(record(), email="info@anderbedrijf.nl")
        official = {"email": r["email"], "branche_meervoud": "hoveniers",
                    "source_url": "https://voorbeeld.nl/contact"}
        pages = [
            ("https://voorbeeld.nl/", "Hovenier Amstel in 5211 AB, tuinonderhoud"),
            ("https://voorbeeld.nl/contact",
             "Contact Hovenier Amstel, 5211 AB, tuinonderhoud. "
             "Zakelijk: info@anderbedrijf.nl"),
        ]
        got = q.inspect_verified(r, official, pages)
        self.assertEqual(got["status"], "verified_with_detail")
        self.assertEqual(got["reason"], "official_email_and_local_activity_confirmed")
        self.assertEqual(got["email_source_url"], official["source_url"])

    def test_cross_domain_not_proven_by_other_page_or_email_substring(self):
        r = dict(record(), email="info@anderbedrijf.nl")
        official = {"email": r["email"], "branche_meervoud": "hoveniers",
                    "source_url": "https://voorbeeld.nl/contact"}
        allowed_home = ("https://voorbeeld.nl/",
                        "Hovenier Amstel 5211 AB met tuinonderhoud")
        rejected = (
            [allowed_home, ("https://voorbeeld.nl/contact",
                           "Hovenier Amstel 5211 AB doet tuinonderhoud. "
                           "mail: anderinfo@anderbedrijf.nl")],
            [("https://voorbeeld.nl/",
              "Hovenier Amstel 5211 AB doet tuinonderhoud. info@anderbedrijf.nl"),
             ("https://voorbeeld.nl/contact",
              "Hovenier Amstel 5211 AB doet tuinonderhoud.")],
            [allowed_home, ("https://ander-site.nl/contact",
                            "Hovenier Amstel 5211 AB doet tuinonderhoud "
                            "info@anderbedrijf.nl")],
        )
        for pages in rejected:
            with self.subTest(pages=pages):
                got = q.inspect_verified(r, official, pages)
                self.assertEqual(got["status"], "needs_manual_check")
                self.assertEqual(got["reason"],
                                 "cross_domain_email_needs_independent_association")

    def test_cross_domain_never_bypasses_locality_activity_or_email_identity(self):
        r = dict(record(), email="info@anderbedrijf.nl")
        official = {"email": r["email"], "branche_meervoud": "hoveniers",
                    "source_url": "https://voorbeeld.nl/contact"}
        cases = [
            [(official["source_url"],
              "Hovenier Amstel doet tuinonderhoud info@anderbedrijf.nl")],
            [(official["source_url"],
              "Amstel 5211 AB is een horecazaak info@anderbedrijf.nl")],
        ]
        for pages in cases:
            with self.subTest(pages=pages):
                got = q.inspect_verified(r, official, pages)
                self.assertEqual(got["status"], "needs_manual_check")
        wrong = dict(official, email="info@another.example")
        got = q.inspect_verified(r, wrong, [
            (official["source_url"], "Hovenier Amstel 5211 AB tuinonderhoud "
             "info@anderbedrijf.nl"),
        ])
        self.assertEqual(got["reason"], "official_identity_email_or_branch_mismatch")

    def test_unrelated_pages_do_not_count_as_official_proof(self):
        result = q.inspect_verified(record(), {
            "email": "info@voorbeeld.nl", "branche_meervoud": "hoveniers",
            "source_url": "https://voorbeeld.nl/"}, [
                ("https://not-voorbeeld.nl/", "Hovenier Amstel 5211 AB tuinonderhoud")])
        self.assertEqual(result["status"], "needs_manual_check")
        self.assertEqual(result["reason"], "source_pages_not_captured")

    def test_captured_verified_site_does_not_fetch_site_twice(self):
        hint = {"name_hint": "Schildersbedrijf Amstel",
                "website_hint": "https://voorbeeld.nl/",
                "category_hint": "painter"}
        page = ('<h1>Schildersbedrijf Amstel</h1>'
                '<p>Amstel doet schilderswerk in 5211 AB.</p>'
                '<a href="mailto:info@voorbeeld.nl">info@voorbeeld.nl</a>')
        session = Mock()
        session.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt") else FakeResponse(page))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            got = verify_official_site(hint, session=session,
                            expected_email="info@voorbeeld.nl", collect_evidence=True)
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(len(got["_captured_pages"]), 1)
        self.assertIn("schilderswerk", got["_captured_pages"][0][1])
        self.assertEqual(got["email"], "info@voorbeeld.nl")

    def test_batch_headers_and_missing_rows_block(self):
        vals = [list(q.APPROVED_COLUMNS),
                ["1","Hovenier Amstel","https://voorbeeld.nl/","info@voorbeeld.nl",
                 "https://voorbeeld.nl/contact","1","hoveniers","Goedendag,",
                 "verified_website_and_email"]]
        with patch.object(q,"_read",return_value=vals):
            got,_=q._input(Mock(),"Approved",1)
        self.assertEqual(got[0]["company"], "Hovenier Amstel")
        with patch.object(q,"_read",return_value=[["corrupt"]]):
            with self.assertRaisesRegex(RuntimeError,"headers"):
                q._input(Mock(),"Approved",1)

    def test_cache_ttl_and_changed_source_force_new_read(self):
        inp=[record()]
        recent=verified()
        with patch.object(q,"_input",return_value=(inp,"hash")), \
             patch.object(q,"_cache_id",return_value=(123,False)), \
             patch.object(q,"_cache",return_value={recent["record_key"]:recent}), \
             patch.object(q,"_persist") as writes:
            result=q.run("Approved",1,conn=Mock(),
                         worker=lambda _:self.fail("should use cached entry"))
        self.assertEqual(result["reused_recent"],1)
        self.assertEqual(result["website_checks"],0)
        writes.assert_not_called()

    def test_changed_private_input_aborts_before_write(self):
        with patch.object(q,"_input",side_effect=[([record()],"before"),([record()],"after")]), \
             patch.object(q,"_cache_id",return_value=(123,True)), \
             patch.object(q,"_persist") as writes:
            with self.assertRaisesRegex(RuntimeError,"changed"):
                q.run("Approved",1,conn=Mock(),worker=lambda _:verified())
        writes.assert_not_called()

    def test_multiple_records_use_parallel_bounded_workers(self):
        from threading import Lock
        lock=Lock()
        concurrent=[0,0]
        def worker(r):
            with lock:
                concurrent[0]+=1
                concurrent[1]=max(concurrent[0],concurrent[1])
            time.sleep(0.008)
            with lock:
                concurrent[0]-=1
            return verified(record_key=r["record_key"])
        rows=[dict(record(),record_key=f"Approved:test-{i}") for i in range(24)]
        with patch.object(q,"_input",return_value=(rows,"hash")), \
             patch.object(q,"_cache_id",return_value=(123,True)), \
             patch.object(q,"_persist"):
            r=q.run("Approved",conn=Mock(),worker=worker)
        self.assertEqual(r["website_checks"],24)
        self.assertGreater(concurrent[1],1)
        self.assertLessEqual(concurrent[1],q.MAX_WORKERS)
        self.assertEqual(r["emails_sent"],0)
        self.assertEqual(r["mailbox_writes"],0)

    def test_google_values_get_missing_values_on_blank_cache_is_valid_empty(self):
        # A valid 200 response on an EMPTY Google Sheet omits "values".
        # Calling _cache via a mocked _read hides this real integration failure.
        client = Mock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "range": "WebsiteEvidence!A1:N1000", "majorDimension": "ROWS"}
        self.assertEqual(q._read(client, "WebsiteEvidence!A1:N1000"), [])
        self.assertEqual(q._cache(client), {})
        with patch.object(q, "_read", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "evidence_source_headers_changed"):
                q._input(client, "Approved", 1)

    def test_interrupted_new_sheet_resumes_without_trusting_empty_data(self):
        with patch.object(q, "_read", return_value=[]):
            self.assertEqual(q._cache(Mock()), {})

    def test_one_pass_preverified_write_reuses_existing_pages_without_network(self):
        row = record()
        row["source_sha256"] = q._digest([
            row["company"], row["website"], row["email"], row["branch"]])
        site = {"company": row["company"], "website": row["website"],
                "email": row["email"], "branche_meervoud": row["branch"],
                "source_url": row["website"],
                "_captured_pages": [(row["website"],
                    "Hovenier Amstel 5211 AB tuinonderhoud en tuinontwerp")]}
        with patch.object(q, "_input", return_value=([row], "sha")) as read, \
             patch.object(q, "_cache_id", return_value=(123, True)), \
             patch.object(q, "_persist") as saved, \
             patch.object(q.requests, "Session") as session:
            output = q.store_preverified_approved([site], conn=Mock())
        self.assertEqual(output["source_rows"], 1)
        self.assertEqual(output["captured_without_refetch"], 1)
        self.assertEqual(output["verified_with_detail"], 1)
        self.assertEqual(read.call_count, 2)
        session.assert_not_called()
        self.assertEqual(saved.call_args.args[3][0]["status"], "verified_with_detail")

    def test_one_pass_input_snapshot_drift_blocks_private_write(self):
        row = record()
        row["source_sha256"] = q._digest([
            row["company"], row["website"], row["email"], row["branch"]])
        site = {"company": row["company"], "website": row["website"],
                "email": row["email"], "branche_meervoud": row["branch"],
                "source_url": row["website"], "_captured_pages": [
                    (row["website"], "Hovenier Amstel 5211 AB tuinontwerp")]}
        with patch.object(q, "_input", side_effect=[([row], "old"),
                                                   ([row], "modified")]), \
             patch.object(q, "_persist") as saved:
            with self.assertRaisesRegex(RuntimeError, "changed_during_review"):
                q.store_preverified_approved([site], conn=Mock())
        saved.assert_not_called()

    def test_one_pass_missing_original_pages_blocks(self):
        row = record()
        site = {"company": row["company"], "website": row["website"],
                "email": row["email"], "branche_meervoud": row["branch"],
                "source_url": row["website"]}
        with patch.object(q, "_input", return_value=([row], "sha")), \
             patch.object(q, "_persist") as saved:
            with self.assertRaisesRegex(RuntimeError, "pages_missing"):
                q.store_preverified_approved([site], conn=Mock())
        saved.assert_not_called()

    def test_automatic_capture_is_off_for_legacy_verifier_users(self):
        hint = {"name_hint": "Schildersbedrijf Amstel",
                "website_hint": "https://voorbeeld.nl/",
                "category_hint": "painter"}
        html = ('<h1>Schildersbedrijf Amstel</h1>'
                '<p>Amstel is een schildersbedrijf 5211 AB.</p>'
                '<a href="mailto:info@voorbeeld.nl">info@voorbeeld.nl</a>')
        client = Mock()
        client.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt")
            else FakeResponse(html))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            got = verify_official_site(hint, session=client,
                                        expected_email="info@voorbeeld.nl")
        self.assertNotIn("_captured_pages", got)

    def test_http_robots_redirect_to_same_site_https_preserves_verification(self):
        hint = {"name_hint": "Schildersbedrijf Amstel",
                "website_hint": "http://voorbeeld.nl/",
                "category_hint": "painter"}
        html = ('<h1>Schildersbedrijf Amstel</h1>'
                '<p>Amstel is een schildersbedrijf in 5211 AB.</p>'
                '<a href="mailto:info@voorbeeld.nl">info@voorbeeld.nl</a>')
        client = Mock()

        def site_get(url, **kw):
            if url == "http://voorbeeld.nl/robots.txt":
                response = FakeResponse(status=301)
                response.headers["Location"] = "https://voorbeeld.nl/robots.txt"
                return response
            if url == "https://voorbeeld.nl/robots.txt":
                return FakeResponse("User-agent: *\nDisallow:\n")
            if url == "http://voorbeeld.nl/":
                response = FakeResponse(status=301)
                response.headers["Location"] = "https://voorbeeld.nl/"
                return response
            if url == "https://voorbeeld.nl/":
                return FakeResponse(html)
            raise AssertionError("unexpected request")

        client.get.side_effect = site_get
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            got = verify_official_site(hint, session=client,
                expected_email="info@voorbeeld.nl", collect_evidence=True)
        self.assertIsNotNone(got)
        self.assertEqual(got["email"], "info@voorbeeld.nl")
        self.assertEqual(client.get.call_count, 4)
        self.assertTrue(all(not c.kwargs.get("allow_redirects") for c in client.get.call_args_list))

    def test_robots_redirect_to_different_domain_is_rejected(self):
        import verify_official_lead as verifier
        client = Mock()
        response = FakeResponse(status=302)
        response.headers["Location"] = "https://anders.nl/robots.txt"
        client.get.return_value = response
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            self.assertIsNone(verifier._robots_policy("http://voorbeeld.nl/", client))
        self.assertEqual(client.get.call_count, 1)

    def test_robots_https_redirect_to_homepage_is_rejected(self):
        import verify_official_lead as verifier
        client = Mock()
        response = FakeResponse(status=301)
        response.headers["Location"] = "https://voorbeeld.nl/"
        client.get.return_value = response
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            self.assertIsNone(verifier._robots_policy("http://voorbeeld.nl/", client))
        self.assertEqual(client.get.call_count, 1)

    def test_large_robots_policy_is_bounded_before_site_fetch(self):
        import verify_official_lead as verifier
        malicious = FakeResponse("x" * 150000)
        client = Mock()
        client.get.return_value = malicious
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            self.assertIsNone(verifier._robots_policy("https://voorbeeld.nl/", client))
        self.assertEqual(client.get.call_count, 1)
        self.assertTrue(client.get.call_args.kwargs["stream"])

    def test_evidence_captures_contact_locality_only_when_homepage_lacks_it(self):
        hint = {"name_hint": "Hovenier Amstel",
                "website_hint": "https://voorbeeld.nl/",
                "category_hint": "landscaper"}
        homepage = ('<h1>Hovenier Amstel</h1><p>tuinonderhoud en tuinontwerp</p>'
                    '<a href="/contact">Contact</a>'
                    '<a href="mailto:info@voorbeeld.nl">info@voorbeeld.nl</a>')
        contact = '<h2>Hovenier Amstel</h2><p>5211 AB Den Bosch</p>'
        client = Mock()
        def site_get(url, **kw):
            if url.endswith("robots.txt"):
                return FakeResponse(status=404)
            return FakeResponse(contact if url.endswith("/contact") else homepage)
        client.get.side_effect = site_get
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            official = verify_official_site(hint, session=client,
                expected_email="info@voorbeeld.nl", collect_evidence=True)
        self.assertEqual(client.get.call_count, 3)
        self.assertEqual(len(official["_captured_pages"]), 2)
        candidate = dict(record(), company="Hovenier Amstel", branch="hoveniers")
        detail = q.inspect_verified(candidate, official, official["_captured_pages"])
        self.assertEqual(detail["status"], "verified_with_detail")

    def test_scheduled_discovery_caps_requests_and_keeps_empty_approved(self):
        import verified_fill
        result = {"approved": [], "complete": False,
                  "counts": {"sites_checked": 240, "approved": 0},
                  "timings": {"total_s": 0.01},
                  "emails_sent": 0, "mailbox_writes": 0}
        from contextlib import redirect_stdout
        from io import StringIO
        with patch.dict("os.environ", {"GITHUB_EVENT_NAME": "schedule",
                                       "REGION": "Nederland", "KEYWORDS": "vakbedrijven",
                                       "RADIUS": "25"}), \
             patch.object(verified_fill, "fill_verified", return_value=result) as discover, \
             patch("approved_handoff.store_approved") as store, \
             redirect_stdout(StringIO()) as output:
            code = verified_fill.main()
        self.assertEqual(code, 2)  # honest PARTIAL is never called complete
        self.assertEqual(discover.call_args.kwargs["max_site_checks"], 240)
        store.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["approved_stored_privately"], 0)

    def test_manual_evidence_has_no_cron_or_mailbox_transport(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        fast = (root / ".github/workflows/fast-website-evidence.yml").read_text()
        new = (root / ".github/workflows/fresh-leads.yml").read_text()
        self.assertIn("github.event_name == 'workflow_dispatch'", fast)
        self.assertIn("github.actor == 'Yolol100'", fast)
        self.assertIn("LEADS_EVIDENCE_V1:REVIEW450_BATCH_1", fast)
        self.assertIn("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", fast)
        for workflow in (fast, new):
            self.assertNotIn("  schedule:", workflow)
            self.assertNotIn("github.event_name == 'schedule'", workflow)
            self.assertNotIn("OUTREACH_MAIL_PASSWORD", workflow)
            self.assertNotIn("smtp", workflow.lower())
        self.assertNotIn("LEADS_EVIDENCE_ONCE:", fast)
        self.assertNotIn("  auto_first_drafts:", new)

    def test_cache_retention_preserves_review450_and_current_batch(self):
        old = verified(checked_at="2025-01-01T00:00:00+00:00")
        history = dict(old, record_key="Review450:history", source_tab="Review450")
        unused = dict(old, record_key="Approved:stale")
        current = verified(record_key="Approved:new", source_sha256="new")
        retained = q._cache_rows_after_retention({
            history["record_key"]: history, unused["record_key"]: unused,
        }, [current])
        self.assertIn("Review450:history", retained)
        self.assertIn("Approved:new", retained)
        self.assertNotIn("Approved:stale", retained)

    def test_expired_trailing_cache_rows_are_cleared_exactly(self):
        old = verified(record_key="Approved:stale",
                       checked_at="2025-01-01T00:00:00+00:00")
        fresh = verified(record_key="Approved:new")
        expected = [list(q.COLUMNS), [str(fresh.get(k, "")) for k in q.COLUMNS]]
        conn = Mock()
        conn.post.return_value.status_code = 200
        with patch.object(q, "_read", return_value=expected) as read:
            q._persist(conn, 345, {old["record_key"]: old}, [fresh])
        request = conn.post.call_args.kwargs["json"]["requests"][0]["updateCells"]
        self.assertEqual(request["range"]["endRowIndex"], 2)
        read.assert_called_once()

    def test_oauth_refresh_failure_is_anonymous_and_blocks(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from google.auth.exceptions import RefreshError
        captured = StringIO()
        with patch("sys.argv", ["evidence.py", "--source", "Approved", "--force"]), \
             patch.object(q, "run", side_effect=RefreshError(
                 "invalid_grant client_email=example-secret@example.invalid")
                          ) as runner, redirect_stdout(captured):
            with self.assertRaises(SystemExit) as error:
                q.main()
        self.assertEqual(error.exception.code, 2)
        runner.assert_called_once_with("Approved", 1, force=True)
        self.assertEqual(json.loads(captured.getvalue()), {
            "status": "blocked", "reason": "google_service_account_auth_failed"})
        self.assertNotIn("example-secret", captured.getvalue())
        self.assertNotIn("invalid_grant", captured.getvalue())

    def test_other_source_errors_are_not_mislabeled_as_google_auth(self):
        from contextlib import redirect_stdout
        from io import StringIO
        captured = StringIO()
        with patch("sys.argv", ["evidence.py", "--source", "Approved"]), \
             patch.object(q, "run", side_effect=RuntimeError(
                 "evidence_source_changed_during_scan")), redirect_stdout(captured):
            with self.assertRaisesRegex(RuntimeError, "source_changed"):
                q.main()
        self.assertEqual(captured.getvalue(), "")

    def test_healthy_evidence_cli_output_is_unchanged(self):
        from contextlib import redirect_stdout
        from io import StringIO
        captured = StringIO()
        result = {"requested": 57, "website_checks": 57,
                  "reused_recent": 0, "verified": 49,
                  "needs_manual_check": 8, "emails_sent": 0,
                  "mailbox_writes": 0}
        with patch("sys.argv", ["evidence.py", "--source", "Approved"]), \
             patch.object(q, "run", return_value=result) as runner, \
             redirect_stdout(captured):
            q.main()
        runner.assert_called_once_with("Approved", 1, force=False)
        self.assertEqual(json.loads(captured.getvalue()), result)

    def test_final_readback_mismatch_blocks(self):
        client=Mock()
        client.post.return_value.status_code=200
        with patch.object(q,"_read",return_value=[["wrong"]]):
            with self.assertRaisesRegex(RuntimeError,"readback"):
                q._persist(client,125,{},[verified()])


if __name__=="__main__":
    unittest.main()
