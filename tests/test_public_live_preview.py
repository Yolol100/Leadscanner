"""Public-safe live preview: privacy, dedupe, evidence and exact review tests."""
import copy
import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from public_live_preview import (
    MAX_VERIFY, PreviewFailed, audit_live_findings, fetch_registry_rows,
    run_live_preview, safe_counts, validate_review_integrity,
)
from outreach_stages import select_reasons, choose_value_actions, generate_mails
from review_draft_stages import prepare_review_batch
from review_selection import build_review_queue


def example():
    return {
        "name_hint": "Example Fictitious Shop", "official_domain": "example.invalid",
        "official_url": "https://example.invalid/", "public_business_email": "info@example.invalid",
        "research_status": "ready", "automatic_send": False,
        "evidence_candidates": [
            {"text": "Klanten kunnen online een afspraak aanvragen voor onderhoud.",
             "source_type": "official_site", "source_url": "https://example.invalid/afspraak", "page_type": "process"},
            {"text": "Vraag online een offerte aan via ons formulier voor maatwerk.",
             "source_type": "official_site", "source_url": "https://example.invalid/offerte", "page_type": "process"},
        ],
    }


class PublicLivePreviewTests(unittest.TestCase):
    def test_safe_counts_never_echo_arbitrary_third_party_values(self):
        out = safe_counts(["hold_no_contact", "info@secret.example", "https://secret.example/", "found"])
        self.assertEqual(out["other"], 2)
        self.assertEqual(out["hold_no_contact"], 1)
        self.assertNotIn("@", repr(out))
        self.assertNotIn("secret", repr(out))

    def test_exact_review_integrity_and_stale_rejection(self):
        reasons = select_reasons({"candidates": [example()]})
        values = choose_value_actions(reasons)
        mail = generate_mails(values)
        batch = prepare_review_batch(mail)
        queue = build_review_queue(batch)
        integrity = validate_review_integrity(batch=batch, queue=queue, official=[])
        self.assertEqual(integrity["tokens_content_bound"], 1)
        self.assertEqual(integrity["tampered_approval_rejected"], 1)
        self.assertEqual(integrity["approved_by_human"], 0)
        self.assertFalse(integrity["external_approval_or_staging"])
        audit = audit_live_findings(
            researched={"candidates": [{"researched_urls": ["https://example.invalid/"],
                                         "evidence_candidates": example()["evidence_candidates"]}]},
            reasons=reasons, mail=mail,
        )
        self.assertGreaterEqual(audit["ranked_findings"], 1)

    def test_real_pipeline_can_run_without_prospect_data_in_report(self):
        filtered = {"candidate_count": 1, "candidates": []}
        source = example()
        source["ready_for_research"] = True
        source["homepage_text_excerpt"] = "Klanten kunnen online een afspraak aanvragen voor onderhoud."
        verified = {"candidate_count": 1, "ready_for_research_count": 1, "candidates": [source]}
        researched = {"candidate_count": 1, "research_ready_count": 1, "candidates": [source]}
        discovered = {"candidate_count": 1, "candidates": []}
        with patch("public_live_preview.fetch_registry_rows", return_value=[{
            "identity": {"company": "different", "domains": set(), "emails": set(), "lead_ids": set()},
            "status": "sent", "row_number": 2,
        }]), patch("public_live_preview.discover", return_value=discovered), \
            patch("public_live_preview.filter_discovery", return_value={"candidate_count": 1, "candidates": [{
                "name_hint": "Example Fictitious Shop", "website_hint": "https://example.invalid/",
                "domain_hint": "example.invalid",
            }], "excluded": []}), \
            patch("public_live_preview.verify_candidates", return_value=verified), \
            patch("public_live_preview.research_candidates", return_value=researched):
            report = run_live_preview(
                registry_url="https://docs.google.com/spreadsheets/example", region="Amsterdam",
                keywords=["fietsenwinkel"], radius_km=3, discovery_limit=5, verify_limit=1,
                run_id=123456, run_number=1, head_sha="a" * 40,
            )
        self.assertEqual(report["counts"]["review_queue"], 1)
        self.assertTrue(report["snapshot_in_memory_valid"])
        self.assertFalse(report["contains_real_recipient_data"])
        self.assertEqual(report["emails_sent"], 0)
        self.assertEqual(report["registry_writes"], 0)
        self.assertEqual(report["review_integrity"]["tampered_approval_rejected"], 1)
        text = repr(report)
        for secret in ("Example Fictitious Shop", "info@example.invalid", "https://example.invalid", "growth-"):
            self.assertNotIn(secret, text)

    def test_bad_registry_fails_before_discovery(self):
        with patch("public_live_preview.discover", side_effect=AssertionError("must_not_discover")):
            with self.assertRaisesRegex(PreviewFailed, "public_live_preview_failed") as cm:
                run_live_preview(
                    registry_url="https://invalid.example/registry", region="Amsterdam",
                    keywords=["fietsenwinkel"], radius_km=5, discovery_limit=10, verify_limit=5,
                    run_id=123, run_number=1, head_sha="a" * 40,
                )
        self.assertEqual(cm.exception.stage, "registry")

    def test_limits_prevent_unbounded_scanning(self):
        with self.assertRaises(PreviewFailed):
            run_live_preview(
                registry_url="https://docs.google.com/spreadsheets/example", region="Amsterdam",
                keywords=["fietsenwinkel"], radius_km=5,
                discovery_limit=1000, verify_limit=MAX_VERIFY + 1,
                run_id=123, run_number=1, head_sha="a" * 40,
            )


if __name__ == "__main__":
    unittest.main()
