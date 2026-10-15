"""No-network acceptance for automatic refill to 100 verified leads.

The verifier is always mocked in refill tests: no real business contact data.
"""
import unittest
from unittest.mock import Mock, patch

from approved_handoff import COLS, HISTORY_COLS, HISTORY_TAB_ID, store_approved, values
from verify_official_lead import category, verify_official_site
from verified_fill import fill_verified, MAX_SITE_CHECKS, MAX_WORKERS


def hint(i):
    return {"overture_id": f"test-{i}", "name_hint": f"Fictief Kapsalon {i}",
            "website_hint": f"https://fictief-{i}.nl/",
            "category_hint": "hair salon"}


def approved(row):
    name = row["name_hint"]
    domain = row["website_hint"].split("/")[2]
    return {"company": name, "website": row["website_hint"],
            "email": f"info@{domain}", "source_url": row["website_hint"],
            "cluster": 2, "branche_meervoud": "kappers",
            "greeting": "Goedendag,", "status": "verified_website_and_email"}


class FakeResponse:
    def __init__(self, text="", status=200, content_type="text/html"):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.content = text.encode()
        self.text = text

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        pass


class WebsiteProofTests(unittest.TestCase):
    def test_belongs_to_official_site_and_email_is_published(self):
        site = hint(1)
        site["name_hint"] = "Schildersbedrijf Amstel"
        site["category_hint"] = "painter"
        html = ('<html><title>Schildersbedrijf Amstel</title><h1>Amstel</h1>'
                '<a href="/contact/">Contact</a></html>')
        contact = '<html><a href="mailto:info@fictief-1.nl">info@fictief-1.nl</a></html>'
        session = Mock()
        def get(url, **kw):
            if url.endswith("/robots.txt"):
                return FakeResponse(status=404)
            return FakeResponse(contact if "/contact/" in url else html)
        session.get.side_effect = get
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            v = verify_official_site(site, session=session)
        self.assertEqual(v["email"], "info@fictief-1.nl")
        self.assertEqual(v["cluster"], 1)
        self.assertEqual(v["source_url"], "https://fictief-1.nl/contact/")
        self.assertEqual(v["greeting"], "Goedendag,")

    def test_named_owner_email_takes_priority_and_proves_greeting(self):
        row = hint(3)
        row["category_hint"] = "painter"
        row["name_hint"] = "Schildersbedrijf Amstel"
        html = ('<h1>Schildersbedrijf Amstel</h1>'
                '<a href="mailto:info@fictief-3.nl">Contact</a>'
                '<a href="mailto:piet@fictief-3.nl">Piet Jansen eigenaar</a>')
        session = Mock()
        session.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt") else FakeResponse(html))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            found = verify_official_site(row, session=session)
        self.assertEqual(found["email"], "piet@fictief-3.nl")
        self.assertEqual(found["greeting"], "Hoi Piet,")
        self.assertEqual(len(values([found], "1234567")), 2)

    def test_category_from_overture_without_official_activity_is_rejected(self):
        row = hint(4)
        row["name_hint"] = "Amstel Service"
        row["category_hint"] = "painter"
        html = '<h1>Amstel Service</h1><p>Wij zijn een fietsenwinkel.</p><a href="mailto:info@fictief-4.nl">Mail</a>'
        session = Mock()
        session.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt") else FakeResponse(html))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            self.assertIsNone(verify_official_site(row, session=session))

    def test_no_published_email_or_wrong_company_never_approved(self):
        site = hint(2)
        session = Mock()
        session.get.side_effect = lambda url, **kw: (
            FakeResponse(status=404) if url.endswith("robots.txt")
            else FakeResponse("<html><h1>Ander Bedrijf</h1></html>"))
        with patch("verify_official_lead.is_public_http_url", return_value=True):
            self.assertIsNone(verify_official_site(site, session=session))
        self.assertIsNone(category({"category_hint": "software agency"}))


class RefillTests(unittest.TestCase):
    def test_continues_searching_until_exactly_100_not_100_hints(self):
        calls = []
        def discoverer(**kwargs):
            calls.append(kwargs["region"])
            # First region has 70 website hints, next 90. Do not query a third.
            offset, number = (0, 70) if len(calls) == 1 else (70, 90)
            return {"candidates": [hint(i) for i in range(offset, offset + number)]}
        def verifier(row):
            # Reject 20% of candidates after visiting the official site.
            return None if int(row["overture_id"].split("-")[1]) % 5 == 0 else approved(row)
        result = fill_verified("Nederland", ["vakbedrijven"], 25,
                               discoverer=discoverer, verifier=verifier,
                               load_registry=lambda: [])
        self.assertEqual(result["counts"]["approved"], 100)
        self.assertEqual(len(result["approved"]), 100)
        self.assertTrue(result["complete"])
        self.assertGreater(result["counts"]["sites_checked"], 100)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["emails_sent"], 0)

    def test_historically_suppressed_company_is_skipped_before_web_requests(self):
        items = [hint(i) for i in range(1, 102)]
        def matcher(identity, registry):
            return {"reason": "opt_out"} if identity["name_hint"] == "Fictief Kapsalon 2" else None
        with patch("verified_fill.match_candidate", side_effect=matcher):
            r = fill_verified("Delft", ["vakbedrijven"], 8,
                discoverer=lambda **k: {"candidates": items},
                verifier=lambda row: approved(row), load_registry=lambda: ["complete"])
        self.assertEqual(r["counts"]["previously_used"], 1)
        self.assertTrue(r["complete"])
        self.assertFalse(any(x["company"] == "Fictief Kapsalon 2" for x in r["approved"]))

    def test_bounded_shortfall_is_reported_honestly_not_faked(self):
        r = fill_verified("Delft", ["vakbedrijven"], 8,
            discoverer=lambda **k: {"candidates": [hint(i) for i in range(10)]},
            verifier=lambda row: None, load_registry=lambda: [])
        self.assertFalse(r["complete"])
        self.assertEqual(r["counts"]["approved"], 0)
        self.assertEqual(r["counts"]["sites_checked"], 10)
        self.assertLessEqual(r["counts"]["sites_checked"], MAX_SITE_CHECKS)
        self.assertLessEqual(MAX_WORKERS, 8)

    def test_registry_unavailable_stops_before_discovery(self):
        discoverer = Mock()
        def fail():
            raise RuntimeError("HMAC state unavailable")
        with self.assertRaisesRegex(RuntimeError, "HMAC"):
            fill_verified("Delft", ["vakbedrijven"], 8,
                discoverer=discoverer, load_registry=fail)
        discoverer.assert_not_called()

    def test_unavailable_sources_not_reported_complete(self):
        with self.assertRaisesRegex(RuntimeError, "source_unavailable"):
            fill_verified("Delft", ["vakbedrijven"], 8,
                discoverer=Mock(side_effect=RuntimeError("down")),
                load_registry=lambda: [])


class ApprovedPrivateHandoffTests(unittest.TestCase):
    @staticmethod
    def fake_sheet(*, existing=None, bad_approved_readback=False,
                   bad_history_readback=False, write_status=200):
        history = [list(HISTORY_COLS)] + list(existing or [])
        snapshot = [list(COLS)]
        appended = []
        calls = []
        session = Mock()

        def get(url, **_kwargs):
            response = Mock(status_code=200)
            if "LeadHistory" in url:
                result = history + appended
                if bad_history_readback and calls:
                    result = result[:-1]
            elif "Approved" in url:
                result = snapshot[:1] if bad_approved_readback else snapshot
            else:
                raise AssertionError("unexpected private URL")
            response.json.return_value = {"values": result}
            return response

        def post(url, **kwargs):
            nonlocal snapshot
            assert url.endswith(":batchUpdate")
            payload = kwargs["json"]
            calls.append(payload)
            response = Mock(status_code=write_status)
            if write_status != 200:
                return response
            operations = payload["requests"]
            snapshot = [
                [cell.get("userEnteredValue", {}).get("stringValue", "")
                 for cell in row["values"]]
                for row in operations[0]["updateCells"]["rows"]
            ]
            while snapshot and not any(snapshot[-1]):
                snapshot.pop()
            if len(operations) > 1:
                assert operations[1]["appendCells"]["sheetId"] == HISTORY_TAB_ID
                for row in operations[1]["appendCells"]["rows"]:
                    appended.append([
                        cell.get("userEnteredValue", {}).get("stringValue", "")
                        for cell in row["values"]
                    ])
            return response

        session.get.side_effect = get
        session.post.side_effect = post
        return session, history, calls

    def test_one_atomic_write_exact_private_readback_and_clear_stale_rows(self):
        data = [approved(hint(i)) for i in range(100)]
        session, history, calls = self.fake_sheet()
        result = store_approved(data, run_id="1234567", session=session)
        self.assertEqual(result, 100)
        session.post.assert_called_once()
        self.assertEqual(session.get.call_count, 3)
        payload = calls[0]
        self.assertEqual(len(payload["requests"]), 2)
        self.assertEqual(len(payload["requests"][0]["updateCells"]["rows"]), 101)
        self.assertEqual(len(payload["requests"][1]["appendCells"]["rows"]), 100)
        self.assertEqual(len(history) + len(calls[0]['requests'][1]['appendCells']['rows']), 101)
        self.assertIn("stringValue", str(payload))
        self.assertNotIn("formulaValue", str(payload))
        self.assertEqual(values([], "1234567"), [list(COLS)])

    def test_empty_result_clears_only_current_snapshot_not_history(self):
        existing = ["older-run", "Fictief Bedrijf", "https://fictief.nl/",
                    "info@fictief.nl", "https://fictief.nl/contact",
                    "verified_lead", "", "2026-10-15T00:00:00Z"]
        session, history, calls = self.fake_sheet(existing=[existing])
        self.assertEqual(store_approved([], run_id="9876543", session=session), 0)
        self.assertEqual(len(calls[0]["requests"]), 1)
        self.assertEqual(history, [list(HISTORY_COLS), existing])
        self.assertEqual(session.get.call_count, 3)

    def test_duplicate_name_domain_or_email_blocks_before_writes(self):
        existing = ["prior", "Fictief Kapsalon 1", "https://fictief-1.nl/",
                    "info@fictief-1.nl", "https://fictief-1.nl/contact",
                    "verified_lead", "", "2026-10-15T00:00:00Z"]
        for field in ("company", "website", "email"):
            with self.subTest(field=field):
                item = approved(hint(5))
                item[field] = {"company": existing[1], "website": existing[2],
                               "email": existing[3]}[field]
                session, _, _ = self.fake_sheet(existing=[existing])
                with self.assertRaisesRegex(RuntimeError, "approved_handoff_unverified"):
                    store_approved([item], run_id="1234567", session=session)
                session.post.assert_not_called()

    def test_incomplete_readback_and_unverified_status_fail(self):
        data = [approved(hint(1))]
        for failure in ("approved", "history", "write"):
            with self.subTest(failure=failure):
                session, _, calls = self.fake_sheet(
                    bad_approved_readback=failure == "approved",
                    bad_history_readback=failure == "history",
                    write_status=500 if failure == "write" else 200)
                with self.assertRaisesRegex(RuntimeError, "approved_handoff_unverified"):
                    store_approved(data, run_id="1234567", session=session)
                self.assertEqual(len(calls), 1)
        data[0]["status"] = "unverified"
        with self.assertRaisesRegex(RuntimeError, "approved_handoff_invalid_row"):
            values(data, "1234567")

    def test_missing_history_stops_before_any_write(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": []}
        session.get.return_value = response
        with self.assertRaisesRegex(RuntimeError, "approved_handoff_unverified"):
            store_approved([approved(hint(1))], run_id="1234567", session=session)
        session.post.assert_not_called()


class AtomicApprovedEvidenceTests(unittest.TestCase):
    """Failure injection at the cross-table transaction boundary (no network)."""

    @staticmethod
    def verified_with_pages():
        row = approved(hint(1))
        row["_captured_pages"] = [(
            row["website"],
            "Fictief Kapsalon 1 5211 AB wij zijn een kapsalon met balayage.")]
        return row

    @staticmethod
    def private_sheet(*, status=200, omit_evidence_after_write=False):
        from fast_website_evidence import COLUMNS
        headers = [list(HISTORY_COLS)]
        state = {
            "approved": [list(COLS)],
            "history": headers[:],
            "evidence": [],
            "commits": 0,
        }
        session = Mock()

        def values_of(cells):
            return [[value.get("userEnteredValue", {}).get("stringValue", "")
                     for value in row["values"]] for row in cells]

        def get(url, **kwargs):
            response = Mock(status_code=200)
            if "?fields=sheets(properties(" in url:
                response.json.return_value = {"sheets": [
                    {"properties": {"title": "WebsiteEvidence", "sheetId": 456}}]}
            elif "LeadHistory" in url:
                response.json.return_value = {"values": state["history"]}
            elif "Approved" in url:
                response.json.return_value = {"values": state["approved"]}
            elif "WebsiteEvidence" in url:
                if omit_evidence_after_write and state["commits"]:
                    response.json.return_value = {"values": [list(COLUMNS)]}
                elif state["evidence"]:
                    response.json.return_value = {"values": state["evidence"]}
                else:
                    # Real Sheets API returns HTTP 200 with no 'values' on blank.
                    response.json.return_value = {"range": "WebsiteEvidence!A1:N"}
            else:
                raise AssertionError("unexpected API read shape")
            return response

        def post(url, **kwargs):
            body = kwargs["json"]
            assert url.endswith(":batchUpdate")
            response = Mock(status_code=status)
            if status != 200:
                return response
            operations = body["requests"]
            assert len(operations) == 3
            assert "updateCells" in operations[0]
            assert "appendCells" in operations[1]
            assert "updateCells" in operations[2]
            state["approved"] = values_of(operations[0]["updateCells"]["rows"])
            while state["approved"] and not any(state["approved"][-1]):
                state["approved"].pop()
            state["history"] += values_of(operations[1]["appendCells"]["rows"])
            state["evidence"] = values_of(operations[2]["updateCells"]["rows"])
            while state["evidence"] and not any(state["evidence"][-1]):
                state["evidence"].pop()
            state["commits"] += 1
            return response

        session.get.side_effect = get
        session.post.side_effect = post
        return session, state

    def test_complete_one_pass_bundle_is_one_transaction_with_exact_readback(self):
        from fast_website_evidence import prepare_new_approved_evidence
        row = self.verified_with_pages()
        expected = values([row], "777")
        facts = prepare_new_approved_evidence([row], expected)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["source_tab"], "Approved")
        client, state = self.private_sheet()
        self.assertEqual(store_approved([row], run_id="777", session=client,
                                        evidence_rows=facts), 1)
        self.assertEqual(state["commits"], 1)
        self.assertEqual(state["approved"], expected)
        self.assertEqual(len(state["history"]), 2)
        self.assertEqual(len(state["evidence"]), 2)
        client.post.assert_called_once()

    def test_evidence_failure_rolls_back_approved_and_history_together(self):
        from fast_website_evidence import prepare_new_approved_evidence
        row = self.verified_with_pages()
        facts = prepare_new_approved_evidence([row], values([row], "777"))
        client, state = self.private_sheet(status=500)
        with self.assertRaisesRegex(RuntimeError, "approved_handoff_unverified"):
            store_approved([row], run_id="777", session=client,
                           evidence_rows=facts)
        self.assertEqual(state["commits"], 0)
        self.assertEqual(state["approved"], [list(COLS)])
        self.assertEqual(state["history"], [list(HISTORY_COLS)])
        self.assertEqual(state["evidence"], [])
        # A safe retry with the same inputs can then commit all tables.
        client, state = self.private_sheet()
        self.assertEqual(store_approved([row], run_id="777", session=client,
                                        evidence_rows=facts), 1)
        self.assertEqual(state["commits"], 1)

    def test_atomic_readback_failure_blocks_automatic_draft_path(self):
        from fast_website_evidence import prepare_new_approved_evidence
        row = self.verified_with_pages()
        facts = prepare_new_approved_evidence([row], values([row], "777"))
        client, state = self.private_sheet(omit_evidence_after_write=True)
        with self.assertRaisesRegex(RuntimeError, "approved_handoff_unverified"):
            store_approved([row], run_id="777", session=client,
                           evidence_rows=facts)
        # The commit happened but its readback cannot be trusted.
        # A later draft runner MUST reject evidence that is absent or stale.
        self.assertEqual(state["commits"], 1)
        self.assertEqual(len(state["history"]), 2)

    def test_reject_missing_original_proof_before_lead_enters_history(self):
        from fast_website_evidence import prepare_new_approved_evidence
        row = self.verified_with_pages()
        del row["_captured_pages"]
        with self.assertRaisesRegex(RuntimeError, "preverified_official_pages_missing"):
            prepare_new_approved_evidence([row], values([row], "777"))


if __name__ == "__main__":
    unittest.main()
