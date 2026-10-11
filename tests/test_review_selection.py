import unittest

from review_draft_stages import prepare_review_batch
from review_selection import (
    build_review_queue,
    parse_approval_tokens,
    render_markdown,
    review_token,
    select_approved,
)


class ReviewSelectionTests(unittest.TestCase):
    def candidate(self, *, company="Acme Fietsen", domain="acmefietsen.nl", email="info@acmefietsen.nl", subject="idee voor jullie afspraakroute", body="Hallo,\n\nExacte body.\n\nGroet,\nAndrew"):
        return {
            "name_hint": company,
            "official_domain": domain,
            "official_url": f"https://{domain}/",
            "public_business_email": email,
            "subject": subject,
            "body": body,
            "mail_status": "ready_for_human_review",
            "copy_validation_status": "green",
            "automatic_send": False,
            "verified_observation": "Klanten kunnen online een afspraak aanvragen.",
            "verified_observation_source_url": f"https://{domain}/afspraak",
            "verified_observation_source_type": "official_site",
            "signal_type": "appointment",
            "value_first_action": "een korte voorbeeldvariant voor de afspraakroute",
        }

    def batch(self):
        return prepare_review_batch({
            "candidates": [
                self.candidate(),
                self.candidate(
                    company="Beta Fietsen",
                    domain="betafietsen.nl",
                    email="info@betafietsen.nl",
                    subject="idee voor jullie aanbod",
                    body="Hallo,\n\nAndere exacte body.\n\nGroet,\nAndrew",
                ),
            ]
        })

    def test_sequence_facts_queue_has_no_mail_and_tokens_bind_to_evidence(self):
        candidate = self.candidate()
        candidate.update({
            "review_mode": "instantly_sequence",
            "mail_status": "ready_for_sequence_review",
            "copy_validation_status": "not_applicable",
            "subject": None,
            "body": None,
            "outreach_status": "ready",
            "value_action_status": "proposed",
        })
        batch = prepare_review_batch({"candidates": [candidate]})
        queue = build_review_queue(batch)
        item = queue["items"][0]
        self.assertEqual(item["review_mode"], "instantly_sequence")
        self.assertEqual(item["subject"], "")
        self.assertEqual(item["body"], "")
        markdown = render_markdown(queue)
        self.assertIn("no separate email written", markdown)
        self.assertNotIn("### Body", markdown)
        token = item["approval_token"]
        self.assertEqual(select_approved(batch, token)["approval"]["approved_count"], 1)
        batch["rows"][0]["verified_observation"] += " changed"
        with self.assertRaisesRegex(ValueError, "unknown_or_stale_approval_token"):
            select_approved(batch, token)

    def test_queue_exposes_exact_review_tokens_and_copy(self):
        batch = self.batch()
        queue = build_review_queue(batch)
        self.assertEqual(queue["review_candidate_count"], 2)
        first = queue["items"][0]
        self.assertEqual(first["approval_token"], review_token(batch["rows"][0]))
        self.assertEqual(first["subject"], batch["rows"][0]["subject"])
        self.assertEqual(first["body"], batch["rows"][0]["body"])
        self.assertFalse(queue["instructions"]["automatic_send"])

    def test_named_contact_sources_survive_review_and_change_invalidates_approval(self):
        candidate = self.candidate(email="jan@acmefietsen.nl")
        candidate.update({
            "contact_person_name": "Jan Jansen",
            "contact_role": "named_owner",
            "email_source_url": "https://acmefietsen.nl/contact",
            "contact_name_source_url": "https://acmefietsen.nl/over-ons",
            "contact_role_source_url": "https://acmefietsen.nl/over-ons",
        })
        batch = prepare_review_batch({"candidates": [candidate]})
        queue = build_review_queue(batch)
        item = queue["items"][0]
        self.assertEqual(item["contact_name_source_url"], "https://acmefietsen.nl/over-ons")
        self.assertEqual(item["contact_role_source_url"], "https://acmefietsen.nl/over-ons")
        self.assertIn("Naam bron: https://acmefietsen.nl/over-ons", render_markdown(queue))
        from review_selection import render_csv
        csv_data = render_csv(queue)
        self.assertIn("contact_name_source_url", csv_data)
        self.assertIn("contact_role_source_url", csv_data)
        token = item["approval_token"]
        batch["rows"][0]["contact_role_source_url"] = "https://acmefietsen.nl/team"
        with self.assertRaisesRegex(ValueError, "unknown_or_stale_approval_token"):
            select_approved(batch, token)

    def test_fourth_finding_not_in_short_draft_still_invalidates_approval(self):
        candidate = self.candidate()
        candidate["selected_findings"] = [{
            "category": "appointment", "priority": "medium", "score": 85 - index,
            "observation": f"Klanten kunnen via de website verschillende afspraakroutes bekijken voor service {index}.",
            "source_url": f"https://acmefietsen.nl/route-{index}",
            "source_type": "official_site", "page_type": "process",
        } for index in range(4)]
        batch = prepare_review_batch({"candidates": [candidate]})
        approval = build_review_queue(batch)["items"][0]["approval_token"]
        self.assertEqual(len(batch["rows"][0]["selected_findings"]), 4)
        batch["rows"][0]["selected_findings"][3]["observation"] += " Nieuwe informatie."
        with self.assertRaisesRegex(ValueError, "unknown_or_stale_approval_token"):
            select_approved(batch, approval)

    def test_review_token_changes_when_copy_changes(self):
        batch = self.batch()
        row = dict(batch["rows"][0])
        original = review_token(row)
        row["body"] = row["body"] + "\nextra"
        self.assertNotEqual(original, review_token(row))

    def test_select_approved_keeps_only_exact_tokens(self):
        batch = self.batch()
        token = review_token(batch["rows"][1])
        result = select_approved(batch, token)
        self.assertEqual(result["draft_candidate_count"], 1)
        self.assertEqual(result["rows"][0]["company"], "Beta Fietsen")
        self.assertEqual(result["approval"]["approved_count"], 1)
        self.assertEqual(result["approval"]["rejected_by_operator_count"], 1)
        self.assertTrue(result["safety"]["approval_token_required"])
        self.assertFalse(result["safety"]["automatic_send"])

    def test_stale_token_is_rejected(self):
        batch = self.batch()
        token = review_token(batch["rows"][0])
        batch["rows"][0]["body"] += "\nchanged after preview"
        with self.assertRaisesRegex(ValueError, "unknown_or_stale_approval_token"):
            select_approved(batch, token)

    def test_duplicate_and_malformed_tokens_fail_closed(self):
        token = review_token(self.batch()["rows"][0])
        with self.assertRaisesRegex(ValueError, "duplicate_approval_token_input"):
            parse_approval_tokens(f"{token},{token}")
        with self.assertRaisesRegex(ValueError, "invalid_approval_token"):
            parse_approval_tokens("all")

    def test_markdown_contains_reviewable_fields(self):
        queue = build_review_queue(self.batch())
        markdown = render_markdown(queue)
        self.assertIn("# Leadscanner review queue", markdown)
        self.assertIn("Approval token:", markdown)
        self.assertIn("Acme Fietsen", markdown)
        self.assertIn("Exacte body.", markdown)


if __name__ == "__main__":
    unittest.main()
