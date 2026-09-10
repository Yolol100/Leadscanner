import unittest
from unittest.mock import patch

import outreach_daily_batch_drafts as daily


def good_state():
    lead_id = "lead-001"
    website = "https://example-machining.com/"
    email = "sales@example-machining.com"
    anchor = "CNC Vertical Machining Services"
    process = "Request a Quote"
    fact = f'I noticed "{anchor}" alongside the "{process}" path on your site.'
    value = f'Around "{anchor}", a short example could ask only for missing request details before your team reviews the quote or intake'
    meta = {
        "automation": daily.PREPARE_AUTOMATION,
        "offer_family": "ai_agent",
        "agent_type": "quote_intake",
        "campaign_target_agent_type": "quote_intake",
        "qualification_tier": "A",
        "customer_potential": "9",
        "business_process": "quote intake",
        "value_asset_type": "process_flow",
        "value_asset_status": "concept_ready",
        "value_asset_summary": value,
        "personalization_anchor": anchor,
        "personalization_process_label": process,
        "personalization_evidence_url": "https://example-machining.com/services/cnc-vertical-machining/",
        "evidence_url": "https://example-machining.com/services/cnc-vertical-machining/",
        "fact": fact,
        "copy_contract": daily.COPY_CONTRACT,
    }
    queue = [{
        "lead_id": lead_id,
        "company": "Example Machining",
        "website": website,
        "email": email,
        "subject": "Quote requests at Example Machining",
        "body": "valid-body-for-mocked-copy-preflight",
        "country": "US",
        "compliance_status": "manual_review",
        "compliance_basis": "",
        "status": "prepared",
        "verification_status": "official_site_ready",
        "opt_out_mode": "reply_optout",
        "sender_email": "info@andrewbaeten.nl",
        "stage": "1",
        "source": "agent_offer:" + __import__("json").dumps(meta),
        "sent_at": "",
        "followup_sent_at": "",
        "message_id": "",
        "followup_message_id": "",
        "reply_at": "",
        "bounce_at": "",
    }]
    candidates = [{
        "candidate_id": lead_id,
        "company": "Example Machining",
        "website": website,
        "source_id": "us-source",
        "country": "US",
        "status": "qualified",
    }]
    qualifications = [{
        "candidate_id": lead_id,
        "status": "qualified",
        "tier": "A",
        "offer_family": "ai_agent",
        "agent_type": "quote_intake",
        "customer_potential": "9",
    }]
    contacts = [{
        "candidate_id": lead_id,
        "email": email,
        "source_url": "https://example-machining.com/contact/",
        "domain_alignment": "aligned",
        "mx_status": "present",
        "status": "ready",
    }]
    sources = [{
        "source_id": "us-source",
        "source_type": "directory_page",
        "source_url": "https://directory.example/manufacturers",
        "country": "US",
        "include_terms": "",
        "exclude_terms": "",
        "max_candidates": "50",
        "approved": "TRUE",
        "enabled": "TRUE",
    }]
    leads = [{"Bedrijf": "Example Machining", "Website": website, "E-mail": email, "Status": "gevonden"}]
    suppressions = []
    return queue, candidates, qualifications, contacts, sources, leads, suppressions


class DailyDraftSelectionTests(unittest.TestCase):
    def test_strong_anchor_rejects_prior_junk_patterns(self):
        bad = [
            "void(0)",
            "Facebook Linkedin Phone Hours Facebook Linkedin",
            "MarathonMT.com",
            "Presenting... Our New Website!",
            "Our Services",
            "Request a Quote",
            "ISO 9001:2015 Certified",
        ]
        for value in bad:
            with self.subTest(value=value):
                self.assertFalse(daily.strong_anchor(value))
        self.assertTrue(daily.strong_anchor("CNC Vertical Machining Services"))
        self.assertTrue(daily.strong_anchor("Custom Hydraulic Filters"))

    def test_stable_test_id_is_per_lead_not_per_day(self):
        a = daily.stable_test_id("lead-001")
        b = daily.stable_test_id("lead-001")
        c = daily.stable_test_id("lead-002")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertRegex(a, r"^daily-lead-draft-[0-9a-f]{24}$")

    @patch.object(daily, "initial_copy_errors", return_value=[])
    def test_happy_path_is_a_only_ready_contact_current_copy(self, _copy):
        state = good_state()
        accepted, rejected = daily.eligible_candidates(
            state[0], agent_type="quote_intake", country="US",
            candidates=state[1], qualifications=state[2], contacts=state[3],
            sources=state[4], leads=state[5], suppressions=state[6],
        )
        self.assertEqual([item.lead_id for item in accepted], ["lead-001"])
        self.assertEqual(rejected, {})

    @patch.object(daily, "initial_copy_errors", return_value=[])
    def test_existing_concept_is_never_selected_again(self, _copy):
        state = list(good_state())
        state[5][0]["Status"] = "concept"
        accepted, rejected = daily.eligible_candidates(
            state[0], agent_type="quote_intake", country="US",
            candidates=state[1], qualifications=state[2], contacts=state[3],
            sources=state[4], leads=state[5], suppressions=state[6],
        )
        self.assertEqual(accepted, [])
        self.assertIn("lead is not new-only in Leadlijst", rejected["lead-001"])

    @patch.object(daily, "initial_copy_errors", return_value=[])
    def test_suppression_terminal_and_b_tier_all_fail_closed(self, _copy):
        for mutation, expected in (
            (lambda s: s[6].append({"email": "sales@example-machining.com", "domain": ""}), "recipient or domain is suppressed"),
            (lambda s: s[0][0].update({"sent_at": "2026-09-10T10:00:00Z"}), "queue row has terminal send/reply/bounce evidence"),
            (lambda s: s[2][0].update({"tier": "B", "customer_potential": "7"}), "qualification tier is not A"),
        ):
            with self.subTest(expected=expected):
                state = list(good_state())
                mutation(state)
                accepted, rejected = daily.eligible_candidates(
                    state[0], agent_type="quote_intake", country="US",
                    candidates=state[1], qualifications=state[2], contacts=state[3],
                    sources=state[4], leads=state[5], suppressions=state[6],
                )
                self.assertEqual(accepted, [])
                self.assertIn(expected, rejected["lead-001"])

    @patch.object(daily, "initial_copy_errors", return_value=[])
    def test_contact_requires_official_site_alignment_mx_and_relevant_role(self, _copy):
        for mutation, expected in (
            (lambda s: s[3][0].update({"mx_status": "unknown"}), "contact MX presence is not proven"),
            (lambda s: s[3][0].update({"domain_alignment": "external_domain"}), "contact domain alignment is not proven"),
            (lambda s: s[3][0].update({"source_url": "https://third-party.example/profile"}), "contact source is not on the official site"),
            (lambda s: (s[0][0].update({"email": "herkerhr@example-machining.com"}), s[3][0].update({"email": "herkerhr@example-machining.com"})), "recipient mailbox role is not suitable for cold business outreach"),
        ):
            with self.subTest(expected=expected):
                state = list(good_state())
                mutation(state)
                accepted, rejected = daily.eligible_candidates(
                    state[0], agent_type="quote_intake", country="US",
                    candidates=state[1], qualifications=state[2], contacts=state[3],
                    sources=state[4], leads=state[5], suppressions=state[6],
                )
                self.assertEqual(accepted, [])
                self.assertIn(expected, rejected["lead-001"])

    @patch.object(daily, "initial_copy_errors", return_value=[])
    def test_source_and_campaign_must_match_current_contract(self, _copy):
        state = list(good_state())
        state[4][0]["approved"] = "FALSE"
        accepted, rejected = daily.eligible_candidates(
            state[0], agent_type="quote_intake", country="US",
            candidates=state[1], qualifications=state[2], contacts=state[3],
            sources=state[4], leads=state[5], suppressions=state[6],
        )
        self.assertEqual(accepted, [])
        self.assertIn("prospect source is not approved and enabled", rejected["lead-001"])

        state = list(good_state())
        accepted, rejected = daily.eligible_candidates(
            state[0], agent_type="commerce", country="US",
            candidates=state[1], qualifications=state[2], contacts=state[3],
            sources=state[4], leads=state[5], suppressions=state[6],
        )
        self.assertEqual(accepted, [])
        self.assertIn("qualification agent does not match campaign", rejected["lead-001"])

    @patch.object(daily, "initial_copy_errors", return_value=[])
    def test_anchor_must_be_specific_agent_relevant_and_used_twice(self, _copy):
        state = list(good_state())
        meta = daily._parse_meta(state[0][0]["source"])
        meta["personalization_anchor"] = "Request a Quote"
        state[0][0]["source"] = "agent_offer:" + __import__("json").dumps(meta)
        accepted, rejected = daily.eligible_candidates(
            state[0], agent_type="quote_intake", country="US",
            candidates=state[1], qualifications=state[2], contacts=state[3],
            sources=state[4], leads=state[5], suppressions=state[6],
        )
        self.assertEqual(accepted, [])
        self.assertIn("personalization anchor is weak or generic", rejected["lead-001"])

    def test_target_and_agent_are_bounded_before_runtime(self):
        with self.assertRaises(ValueError):
            daily.process(target=51, agent_type="quote_intake", country="US", run_key="test", count_only=True)
        with self.assertRaises(ValueError):
            daily.process(target=1, agent_type="auto", country="US", run_key="test", count_only=True)


if __name__ == "__main__":
    unittest.main()
