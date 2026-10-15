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

    def test_previously_existing_functions_are_only_mentions(self):
        class CaptureFake:
            pages = [("https://voorbeeld.nl/", "Hovenier Amstel 5211 AB "
                      "tuinonderhoud en tuinontwerp, online boeken en offertevragen")]
            def close(self): pass
        with patch.object(q, "Capture", return_value=CaptureFake()), \
             patch.object(q, "verify_official_site", return_value={
                 "email":"info@voorbeeld.nl", "branche_meervoud":"hoveniers",
                 "source_url":"https://voorbeeld.nl/"}):
            out = q.inspect(record())
        self.assertEqual(out["status"], "verified_with_detail")
        signal = json.loads(out["feature_mentions_json"])[0]
        self.assertEqual(signal["certainty"], "text_mention_only")
        self.assertIn("source_url", signal)

    def test_wrong_branch_or_unconfirmed_email_fails_closed(self):
        class CaptureFake:
            pages = [("https://voorbeeld.nl/", "Hovenier Amstel 5211 AB tuinonderhoud")]
            def close(self): pass
        with patch.object(q, "Capture", return_value=CaptureFake()), \
             patch.object(q, "verify_official_site", return_value=None):
            self.assertEqual(q.inspect(record())["status"], "needs_manual_check")
        with patch.object(q, "Capture", return_value=CaptureFake()), \
             patch.object(q, "verify_official_site", return_value={
                 "email":"info@voorbeeld.nl", "branche_meervoud":"schilders",
                 "source_url":"https://voorbeeld.nl/"}):
            self.assertEqual(q.inspect(record())["reason"], "branch_mismatch")

    def test_cross_domain_email_requires_extra_review(self):
        r = record()
        r["email"] = "info@anderbedrijf.nl"
        class CaptureFake:
            pages = [("https://voorbeeld.nl/", "Hovenier Amstel 5211 AB tuinonderhoud")]
            def close(self): pass
        with patch.object(q, "Capture", return_value=CaptureFake()), \
             patch.object(q, "verify_official_site", return_value={
                 "email":r["email"], "branche_meervoud":"hoveniers",
                 "source_url":"https://voorbeeld.nl/contact"}):
            out=q.inspect(r)
        self.assertEqual(out["status"], "needs_manual_check")
        self.assertEqual(out["reason"], "cross_domain_email_needs_independent_association")

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

    def test_final_readback_mismatch_blocks(self):
        client=Mock()
        client.post.return_value.status_code=200
        with patch.object(q,"_read",return_value=[["wrong"]]):
            with self.assertRaisesRegex(RuntimeError,"readback"):
                q._persist(client,125,{},[verified()])


if __name__=="__main__":
    unittest.main()
