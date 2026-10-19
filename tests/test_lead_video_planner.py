"""Offline-only tests. 100% fictieve websites en personen."""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lead_video_planner import (route_verified_leads, render_short_email,
                                prepare_video_storyboard, OPT_OUT)

STAMP = "2026-10-19T12:00:00+00:00"

def lead(i, video=False):
    base = f"https://bedrijf{i}.example/"
    return dict(company=f"Fictieve Zaak {i}", website=base,
                official_contact_url=base + "contact", email=f"info@bedrijf{i}.example",
                status="verified_website_and_email", suppressed=False,
                prior_contact=False, email_first_party_verified=True,
                approved_source_verified=True,
                video_opportunity=(dict(verified=True, business_impact_reviewed=True,
                                        evidence_type="official_site_observation", source_url=base,
                                        checked_at=STAMP, observed="Duidelijk zichtbaar verbeterpunt")
                                   if video else None))


def mail(**changes):
    x = dict(website="https://salon.example/", source_url="https://salon.example/contact",
             checked_at=STAMP, source_excerpt="U kunt telefonisch een afspraak maken.",
             observation="Ik zag dat klanten bij jullie telefonisch een afspraak kunnen maken.",
             question="Zou het handig zijn als klanten ook zelf online een behandeling en tijdstip kunnen kiezen?",
             subject="Korte vraag over jullie afspraken",
             inspected_pages=["https://salon.example/", "https://salon.example/contact"],
             relevance_reviewed=True, feature_already_available=False,
             verified_official_source=True)
    x.update(changes)
    return x


def findings():
    return [dict(verified=True, source_url=f"https://salon.example/{n}",
                 checked_at=STAMP, observed="een knelpunt in de klantreis",
                 change="een duidelijkere klantactie") for n in ("", "contact")]


class RouteTests(unittest.TestCase):
    def test_six_video_hints_caps_five_and_remaining_is_mail(self):
        result = route_verified_leads([lead(i, True) for i in range(1, 7)],
                                      requested=6, suppression_complete=True)
        self.assertEqual([r["company"] for r in result["video"]],
                         [f"Fictieve Zaak {i}" for i in range(1, 6)])
        self.assertEqual(len(result["email"]), 1)
        self.assertNotIn("score", result["email"][0])

    def test_later_strong_video_outranks_earlier_possible(self):
        rows = [lead(i, True) for i in range(1, 9)]
        for row in rows[:6]:
            row["video_opportunity"]["priority_band"] = "possible"
        for row in rows[6:]:
            row["video_opportunity"]["priority_band"] = "strong"
        result = route_verified_leads(rows, requested=8, suppression_complete=True)
        self.assertEqual([r["company"] for r in result["video"]],
                         ["Fictieve Zaak 7", "Fictieve Zaak 8", "Fictieve Zaak 1",
                          "Fictieve Zaak 2", "Fictieve Zaak 3"])
        self.assertEqual(len(result["email"]), 3)
        self.assertTrue(all("score" not in r for r in result["email"]))

    def test_weak_opportunity_not_forced_into_video(self):
        row = lead(1, True)
        row["video_opportunity"]["priority_band"] = "weak"
        result = route_verified_leads([row], requested=1, suppression_complete=True)
        self.assertEqual(len(result["video"]), 0)
        self.assertEqual(len(result["email"]), 1)

    def test_unrecognized_priority_is_blocked(self):
        row = lead(1, True)
        row["video_opportunity"]["priority_band"] = "guaranteed_leads"
        with self.assertRaisesRegex(ValueError, "video_priority_band_invalid"):
            route_verified_leads([row], requested=1, suppression_complete=True)

    def test_malformed_qualitative_priority_fails_safely(self):
        row = lead(1, True)
        row["video_opportunity"]["priority_band"] = ["strong"]
        with self.assertRaisesRegex(ValueError, "video_priority_band_invalid"):
            route_verified_leads([row], requested=1, suppression_complete=True)

    def test_ordinary_leads_preserve_discovery_order(self):
        rows = [lead(i, True) for i in range(1, 8)]
        rows[-1]["video_opportunity"]["priority_band"] = "strong"
        result = route_verified_leads(rows, requested=7, suppression_complete=True)
        self.assertEqual([r["company"] for r in result["email"]],
                         ["Fictieve Zaak 5", "Fictieve Zaak 6"])

    def test_priority_tie_preserves_input_order(self):
        rows = [lead(i, True) for i in (6, 5, 4, 3, 2, 1)]
        result = route_verified_leads(rows, requested=6, suppression_complete=True)
        self.assertEqual([r["company"] for r in result["video"]],
                         [f"Fictieve Zaak {i}" for i in (6, 5, 4, 3, 2)])

    def test_unsuppressed_plain_route_no_score(self):
        r = route_verified_leads([lead(1)], requested=2, suppression_complete=True)
        self.assertEqual((len(r["video"]), len(r["email"])), (0, 1))

    def test_missing_registry_is_hard_fail(self):
        with self.assertRaises(RuntimeError):
            route_verified_leads([lead(1)], requested=1, suppression_complete=False)

    def test_previous_contact_suppressed(self):
        r = lead(1)
        r["prior_contact"] = True
        v = route_verified_leads([r], requested=1, suppression_complete=True)
        self.assertEqual((len(v["email"]), len(v["skipped"])), (0, 1))

    def test_missing_verified_contact_is_skipped(self):
        r = lead(1)
        r["email_first_party_verified"] = False
        v = route_verified_leads([r], requested=1, suppression_complete=True)
        self.assertEqual(len(v["skipped"]), 1)

    def test_duplicate_domain_fails(self):
        a, b = lead(1), lead(1)
        with self.assertRaises(RuntimeError):
            route_verified_leads([a, b], requested=2, suppression_complete=True)

    def test_forged_video_evidence_fails(self):
        r = lead(1, True)
        r["video_opportunity"]["verified"] = False
        with self.assertRaises(ValueError):
            route_verified_leads([r], requested=1, suppression_complete=True)

    def test_low_dr_alone_is_not_site_proof(self):
        r = lead(1, True)
        r["video_opportunity"]["evidence_type"] = "low_domain_rating"
        with self.assertRaises(ValueError):
            route_verified_leads([r], requested=1, suppression_complete=True)

    def test_video_business_impact_must_be_reviewed(self):
        r = lead(1, True)
        r["video_opportunity"]["business_impact_reviewed"] = False
        with self.assertRaises(ValueError):
            route_verified_leads([r], requested=1, suppression_complete=True)

    def test_hundred_verified_no_automatic_video_if_no_evidence(self):
        rows = [lead(i, i <= 5) for i in range(1, 101)]
        result = route_verified_leads(rows, requested=100, suppression_complete=True)
        self.assertEqual((len(result["video"]), len(result["email"])), (5, 95))
        self.assertTrue(all("score" not in item for item in result["email"]))

    def test_unknown_contact_state_skipped(self):
        r = lead(1)
        r["prior_contact"] = None
        res = route_verified_leads([r], requested=1, suppression_complete=True)
        self.assertEqual((len(res["skipped"]), len(res["video"]), len(res["email"])), (1, 0, 0))

    def test_other_domain_proof_fails(self):
        r = lead(1, True)
        r["video_opportunity"]["source_url"] = "https://another.example/"
        with self.assertRaises(ValueError):
            route_verified_leads([r], requested=1, suppression_complete=True)

    def test_malformed_business_email_fails(self):
        r = lead(1)
        r["email"] = "info@@bedrijf1.example"
        with self.assertRaises(RuntimeError):
            route_verified_leads([r], requested=1, suppression_complete=True)

    def test_forged_official_contact_url_fails(self):
        r = lead(1)
        r["official_contact_url"] = "https://foreign.example/contact"
        with self.assertRaises(RuntimeError):
            route_verified_leads([r], requested=1, suppression_complete=True)

    def test_requested_limit(self):
        with self.assertRaises(ValueError):
            route_verified_leads([], requested=101, suppression_complete=True)


class MailTests(unittest.TestCase):
    def test_exact_template_and_opt_out(self):
        result = render_short_email(**mail())
        self.assertEqual(result["body"],
                         "Goedendag,\n\nIk zag dat klanten bij jullie telefonisch een afspraak kunnen maken.\n\n"
                         "Zou het handig zijn als klanten ook zelf online een behandeling en tijdstip kunnen kiezen?\n\n"
                         + OPT_OUT + "\n\nGroet,\nAndrew")
        self.assertNotIn("Webactueel", result["body"])
        self.assertLessEqual(len(result["body"].split()), 110)

    def test_refuse_feature_already_available(self):
        for state in (True, None):
            with self.subTest(state=state), self.assertRaises(ValueError):
                render_short_email(**mail(feature_already_available=state))

    def test_refuse_four_pages(self):
        pages = [f"https://salon.example/p/{i}" for i in range(4)]
        with self.assertRaises(ValueError):
            render_short_email(**mail(inspected_pages=pages))

    def test_refuse_uninspected_source(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(source_url="https://salon.example/extra"))

    def test_refuse_external_source(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(inspected_pages=["https://salon.example/contact", "https://evil.example/"]))

    def test_refuse_unreviewed_claim(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(relevance_reviewed=False))

    def test_refuse_sales_subject(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(subject="Gratis AI-deal"))

    def test_refuse_multiple_ctas(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(question="Zou het handig zijn als mensen online boeken? En gratis advies?"))

    def test_refuse_future_evidence(self):
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        with self.assertRaises(ValueError):
            render_short_email(**mail(checked_at=future))

    def test_refuse_unrelated_excerpt(self):
        with self.assertRaisesRegex(ValueError, "observation_not_grounded"):
            render_short_email(**mail(source_excerpt="Wij verkopen uitsluitend antieke meubels."))

    def test_refuse_negative_unverified_claim(self):
        with self.assertRaisesRegex(ValueError, "negative_observation"):
            render_short_email(**mail(observation="Ik zag dat klanten geen afspraak kunnen maken, alleen telefonisch."))

    def test_refuse_brand_name_in_subject(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(subject="webactueel afspraak idee"))

    def test_refuse_unicode_header_control(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(subject="Korte vraag\u202eekaf"))

    def test_refuse_ip_source(self):
        with self.assertRaises(ValueError):
            render_short_email(**mail(inspected_pages=["https://salon.example/contact", "http://127.0.0.1/"]))

    def test_stale_website_observation_rejected(self):
        stale = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        with self.assertRaises(ValueError):
            render_short_email(**mail(checked_at=stale))

    def test_no_send_transport_import(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "lead_video_planner.py").read_text()
        for unwanted in ("import smtplib", "import imaplib", "requests.get", "subprocess", "send_message("):
            self.assertNotIn(unwanted, source)


class ScriptTests(unittest.TestCase):
    def test_real_evidence_produces_screen_instructions(self):
        storyboard = prepare_video_storyboard(
            website="https://salon.example/", findings=findings(),
            ahrefs=dict(country="NL", checked_at=STAMP, keyword="pedicure Breda", position=18, target_url="https://salon.example/", ranking_url="https://salon.example/pedicure"),
            competitor=dict(verified=True, same_service_and_region=True, source_url="https://rivaal.example/behandelingen",
                            checked_at=STAMP, observed="een duidelijke afspraakknop"))
        self.assertEqual(len(storyboard["scenes"]), 5)
        self.assertIn("positie 18", storyboard["scenes"][2]["say"])
        self.assertEqual(storyboard["status"], "owner_review_required")

    def test_no_ahrefs_does_not_invent_numbers(self):
        res = prepare_video_storyboard(website="https://salon.example/", findings=findings(),
                                      ahrefs=None, competitor=None)
        self.assertIn("niet onderzocht", res["scenes"][2]["screen"])

    def test_ahrefs_without_date_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare_video_storyboard(website="https://salon.example/", findings=findings(),
                                    ahrefs=dict(country="NL", keyword="pedicure", position=4, target_url="https://salon.example/", ranking_url="https://salon.example/pedicure"), competitor=None)

    def test_competitor_never_same_site(self):
        with self.assertRaises(ValueError):
            prepare_video_storyboard(website="https://salon.example/", findings=findings(),
                                    ahrefs=None, competitor=dict(verified=True, same_service_and_region=True,
                                       source_url="https://salon.example/ander", checked_at=STAMP,
                                       observed="goed formulier"))

    def test_wrong_ahrefs_target_fails(self):
        with self.assertRaises(ValueError):
            prepare_video_storyboard(website="https://salon.example/", findings=findings(),
                                    ahrefs=dict(country="NL", checked_at=STAMP,
                                                keyword="pedicure", position=3,
                                                target_url="https://foreign.example/",
                                                ranking_url="https://foreign.example/pedicure"), competitor=None)

    def test_wrong_ahrefs_ranking_page_fails(self):
        with self.assertRaises(ValueError):
            prepare_video_storyboard(website="https://salon.example/", findings=findings(),
                                    ahrefs=dict(country="NL", checked_at=STAMP,
                                                keyword="pedicure", position=3,
                                                target_url="https://salon.example/",
                                                ranking_url="https://foreign.example/pedicure"), competitor=None)

    def test_competitor_unrelated_market_fails(self):
        with self.assertRaises(ValueError):
            prepare_video_storyboard(website="https://salon.example/", findings=findings(),
                                    ahrefs=None,
                                    competitor=dict(verified=True, same_service_and_region=False,
                                                    source_url="https://foreign.example/", checked_at=STAMP,
                                                    observed="een heldere klantenroute"))

    def test_cross_host_finding_rejected(self):
        ff = findings()
        ff[0]["source_url"] = "https://elsewhere.example/"
        with self.assertRaises(ValueError):
            prepare_video_storyboard(website="https://salon.example/", findings=ff,
                                    ahrefs=None, competitor=None)


if __name__ == "__main__":
    unittest.main()