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


class FastOfficialEvidenceTests(unittest.TestCase):
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

    def test_interrupted_new_sheet_resumes_without_trusting_empty_data(self):
        with patch.object(q, "_read", return_value=[]):
            self.assertEqual(q._cache(Mock()), {})

    def test_one_pass_preverified_write_reuses_existing_pages_without_network(self):
        row = record()
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
        site = {"company": row["company"], "website": row["website"],
                "email": row["email"], "branche_meervoud": row["branch"],
                "source_url": row["website"], "_captured_pages": []}
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

    def test_scheduled_automation_never_invokes_mailbox_transport(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        fast = (root / ".github/workflows/fast-website-evidence.yml").read_text()
        new = (root / ".github/workflows/fresh-leads.yml").read_text()
        self.assertIn("github.event_name == 'schedule'", fast)
        self.assertIn("github.event_name == 'schedule'", new)
        self.assertIn("LEADS_EVIDENCE_ONCE:", fast)
        self.assertIn("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", fast)
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", fast)
        research, drafts = new.split("  auto_first_drafts:", 1)
        self.assertNotIn("OUTREACH_MAIL_PASSWORD", research)
        self.assertIn("OUTREACH_MAIL_PASSWORD", drafts)
        self.assertIn("github.event_name == 'schedule'", drafts)
        self.assertNotIn("smtp", fast.lower() + research.lower())

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

    def test_final_readback_mismatch_blocks(self):
        client=Mock()
        client.post.return_value.status_code=200
        with patch.object(q,"_read",return_value=[["wrong"]]):
            with self.assertRaisesRegex(RuntimeError,"readback"):
                q._persist(client,125,{},[verified()])


if __name__=="__main__":
    unittest.main()
