import unittest
from pathlib import Path

from approval_revalidation import revalidate_approved
from dedupe_preflight import candidate_identity
from outreach_stages import choose_value_actions, generate_mails, generate_sequence_facts, select_reasons
from review_draft_stages import prepare_review_batch
from review_selection import build_review_queue, select_approved


class PipelineContractScenarioTests(unittest.TestCase):
    def test_workflow_routes_fact_only_approval_to_fingerprint_guard(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/leads-cold.yml").read_text(encoding="utf-8")
        self.assertIn("INPUT_INSTANTLY_SEQUENCE_APPROVAL: ${{ inputs.instantly_sequence_approval }}", workflow)
        self.assertIn("sequence_approval=os.environ.get('INPUT_INSTANTLY_SEQUENCE_APPROVAL', '')", workflow)
        self.assertIn("if: inputs.execution_mode == 'draft'\n        run: |", workflow)
        self.assertIn("instantly_sequence_cannot_be_stored_as_mailbox_drafts", workflow)


    def candidate(self, *, source_type="official_site", evidence_text=None):
        return {
            "name_hint": "Acme Fietsen",
            "official_domain": "acmefietsen.nl",
            "official_url": "https://acmefietsen.nl/",
            "public_business_email": "info@acmefietsen.nl",
            "research_status": "ready",
            "evidence_candidates": [{
                "text": evidence_text or (
                    "Klanten kunnen online een werkplaatsafspraak aanvragen "
                    "voor onderhoud of reparatie."
                ),
                "source_url": "https://acmefietsen.nl/afspraak",
                "source_type": source_type,
                "page_type": "process",
            }],
        }

    def build_approved(self):
        selected = select_reasons({"candidates": [self.candidate()]})
        self.assertEqual(selected["ready_count"], 1)
        valued = choose_value_actions(selected)
        mails = generate_mails(valued)
        self.assertEqual(mails["ready_for_human_review_count"], 1)
        batch = prepare_review_batch(mails)
        queue = build_review_queue(batch)
        self.assertEqual(queue["review_candidate_count"], 1)
        return select_approved(batch, queue["items"][0]["approval_token"])

    def test_evidence_only_path_approves_facts_without_generating_copy(self):
        selected = select_reasons({"candidates": [self.candidate()]})
        valued = choose_value_actions(selected)
        facts = generate_sequence_facts(valued)
        self.assertEqual(facts["ready_for_human_review_count"], 1)
        batch = prepare_review_batch(facts)
        queue = build_review_queue(batch)
        self.assertEqual(queue["review_candidate_count"], 1)
        approved = select_approved(batch, queue["items"][0]["approval_token"])
        revalidated = revalidate_approved(approved, [])
        self.assertEqual(revalidated["remaining_count"], 1)
        row = revalidated["rows"][0]
        self.assertEqual(row["review_mode"], "instantly_sequence")
        self.assertEqual(row["subject"], "")
        self.assertEqual(row["body"], "")
        self.assertFalse(row["automatic_send"])

    def test_positive_signal_reaches_exact_approval_and_live_revalidation(self):
        approved = self.build_approved()
        current = revalidate_approved(approved, [])
        self.assertEqual(current["remaining_count"], 1)
        row = current["rows"][0]
        self.assertEqual(row["signal_type"], "appointment")
        self.assertFalse(row["automatic_send"])
        self.assertTrue(current["safety"]["dedupe_rechecked_immediately_before_mutation"])

    def test_post_preview_registry_match_suppresses_approved_lead(self):
        approved = self.build_approved()
        row = approved["rows"][0]
        registry = [{
            "identity": candidate_identity({
                "company": row["company"],
                "domain": row["official_domain"],
                "emails": row["email"],
                "lead_ids": "growth-ffffffffffffffffffff",
            }),
            "status": "sent",
            "row_number": 2,
        }]
        current = revalidate_approved(approved, registry)
        self.assertEqual(current["remaining_count"], 0)
        self.assertEqual(current["suppressed_after_preview_count"], 1)

    def test_generic_marketing_copy_never_becomes_outreach(self):
        selected = select_reasons({
            "candidates": [self.candidate(
                evidence_text="Kwaliteit en goede service staan centraal bij al onze werkzaamheden."
            )]
        })
        self.assertEqual(selected["ready_count"], 0)
        mails = generate_mails(choose_value_actions(selected))
        batch = prepare_review_batch(mails)
        self.assertEqual(batch["draft_candidate_count"], 0)

    def test_third_party_evidence_never_becomes_outreach(self):
        selected = select_reasons({"candidates": [self.candidate(source_type="directory")]})
        self.assertEqual(selected["ready_count"], 0)
        mails = generate_mails(choose_value_actions(selected))
        self.assertEqual(mails["ready_for_human_review_count"], 0)


    def test_default_mail_mode_matches_operator_documentation(self):
        from pathlib import Path
        from re import search
        root=Path(__file__).resolve().parents[1]
        workflow=(root/".github/workflows/leads-cold.yml").read_text(encoding="utf-8")
        mode=search(r"(?s)preview_copy_mode:.*?default: *(reviewed_mail|instantly_sequence)",workflow)
        self.assertIsNotNone(mode)
        self.assertEqual(mode.group(1),"reviewed_mail")
        for path in ("README.md","AGENTS.md"):
            documentation=(root/path).read_text(encoding="utf-8")
            self.assertIn("preview_copy_mode=reviewed_mail`",documentation)
            self.assertIn("default",documentation.casefold())
            self.assertNotIn("preview_copy_mode=instantly_sequence` (default)",documentation)


if __name__ == "__main__":
    unittest.main()
