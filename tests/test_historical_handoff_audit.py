"""Aggregate-only eligibility checks for existing reviewed Instantly drafts."""
import unittest
from copy import deepcopy

from historical_handoff_audit import audit_counts, _reviewed_refresh, audit_destination_copies

BODY = (
    "Hoi, ik zag op jullie website dat klanten een afspraak kunnen maken. "
    "Ik kan een kort voorbeeld sturen om de afspraakroute duidelijker te maken. "
    "Met vriendelijke groet, Andrew Baeten"
)


def row(index: int = 0, *, status: str = "candidate_review_required") -> dict:
    values = {
        "leadscanner_contact_basis": "review_required",
        "leadscanner_source_lead_id": "source-" + str(index),
        "leadscanner_site_refresh_status": status,
        "leadscanner_site_refresh_subject": "Een idee voor jullie website",
        "leadscanner_site_refresh_body": BODY,
        "leadscanner_site_refresh_observation": "Klanten kunnen via de website online een afspraak maken.",
        "leadscanner_site_refresh_value_action": "een korte verbetering van de afspraakroute",
        "leadscanner_site_refresh_evidence_url": "https://studio-example.org/afspraak",
        "leadscanner_site_refresh_source_type": "official_site",
        "leadscanner_site_refresh_signal_type": "appointment",
        "leadscanner_site_refresh_contact_url": "https://studio-example.org/contact",
        "leadscanner_site_refresh_official_domain": "studio-example.org",
        "leadscanner_site_refresh_checked_date": "2026-10-12",
    }
    return {
        "email": "person" + str(index) + "@studio-example.org",
        "id": "row-" + str(index),
        "list_id": "source-id",
        "campaign": None,
        "status": 0,
        "payload": values,
    }


class HistoricalHandoffAuditTests(unittest.TestCase):
    def test_sourced_website_copy_classifies_without_exposing_recipient(self):
        language, hold = _reviewed_refresh(row())
        self.assertEqual((language, hold), ("nl", ""))
        bad = row()
        bad["payload"]["leadscanner_site_refresh_contact_url"] = "https://other.example/contact"
        self.assertEqual(_reviewed_refresh(bad), ("", "unverified_evidence"))
        missing = row()
        missing["payload"]["leadscanner_site_refresh_body"] = ""
        self.assertEqual(_reviewed_refresh(missing), ("", "incomplete_review"))

    def test_research_without_recipient_is_not_ready_to_stage(self):
        p = row(status="research_only_contact_unverified")
        self.assertEqual(_reviewed_refresh(p), ("", "research_only"))
        p["status"] = -1
        self.assertEqual(_reviewed_refresh(p), ("", "suppressed"))

    def test_all_1128_partition_and_provider_holds_are_anonymous(self):
        rows = [row()] + [
            row(i, status="research_only_contact_unverified")
            for i in range(1, 1128)
        ]
        report = audit_counts(
            rows, [], set(), {"nl": set(), "en": set()}, {"nl": True, "en": True}
        )
        self.assertEqual(report["counts"]["source_total"], 1128)
        self.assertEqual(report["counts"]["review_candidate"], 1)
        self.assertEqual(report["counts"]["stage_eligible_review_only"], 1)
        self.assertEqual(report["counts"]["research_only"], 1127)
        self.assertFalse(report["provider_mutation"])
        self.assertFalse(report["automatic_send"])
        self.assertNotIn("person0", str(report))
        blocked = audit_counts(
            rows, [], {"person0@studio-example.org"},
            {"nl": set(), "en": set()}, {"nl": True, "en": True},
        )
        self.assertEqual(blocked["counts"]["provider_suppression_hold"], 1)
        self.assertEqual(blocked["counts"]["stage_eligible_review_only"], 0)

    def test_private_destination_reconciliation_distinguishes_partial_and_exact(self):
        from historical_handoff_stage import build_destination_variables
        from instantly_campaign_copy import TARGET_CAMPAIGNS
        source = row()
        source["payload"]["leadscanner_import_origin"] = "myhost_drafts"
        target = deepcopy(source)
        target["id"] = "copied-id-01"
        target["campaign"] = TARGET_CAMPAIGNS["nl"][0]
        target["list_id"] = None
        class Client:
            def __init__(self):
                self.current = target
            def get_lead(self, id):
                self.assert_id = id
                return deepcopy(self.current)
        client = Client()
        destinations = {"nl": {source["email"]: target}, "en": {}}
        status = audit_destination_copies([source], destinations, client)
        self.assertEqual(status["copied_pending_personalization"], 1)
        self.assertEqual(status["exact_personalization_verified"], 0)
        self.assertNotIn(source["email"], str(status))
        client.current["payload"] = build_destination_variables(source, target)
        exact = audit_destination_copies([source], destinations, client)
        self.assertEqual(exact["exact_personalization_verified"], 1)
        self.assertEqual(exact["copied_pending_personalization"], 0)
        client.current["payload"]["leadscanner_body"] = "changed"
        mismatched = audit_destination_copies([source], destinations, client)
        self.assertEqual(mismatched["changed_or_unexpected_personalization"], 1)

    def test_wrong_destination_or_unknown_person_never_counts_as_completed(self):
        from instantly_campaign_copy import TARGET_CAMPAIGNS
        s = row()
        s["payload"]["leadscanner_import_origin"] = "myhost_drafts"
        dest = deepcopy(s)
        dest["id"] = "copy-other"
        dest["campaign"] = TARGET_CAMPAIGNS["en"][0]
        class Client:
            def get_lead(self, id):
                return deepcopy(dest)
        result = audit_destination_copies([s], {"nl": {}, "en": {s["email"]: dest}}, Client())
        self.assertEqual(result["unexpected_source_or_language"], 1)
        self.assertEqual(result["exact_personalization_verified"], 0)

    def test_handoff_not_eligible_for_active_or_unready_campaign(self):
        rows = [row()] + [row(i, status="") for i in range(1, 1128)]
        audit = audit_counts(
            rows, [], set(), {"nl": set(), "en": set()}, {"nl": False, "en": True}
        )
        self.assertEqual(audit["counts"]["campaign_not_ready"], 1)
        self.assertEqual(audit["counts"]["stage_eligible_review_only"], 0)

    def test_already_in_target_skips_duplicate_and_bad_source_size_fails(self):
        rows = [row()] + [row(i, status="") for i in range(1, 1128)]
        result = audit_counts(
            rows, [], set(),
            {"nl": {"person0@studio-example.org"}, "en": set()},
            {"nl": True, "en": True},
        )
        self.assertEqual(result["counts"]["already_in_target"], 1)
        self.assertEqual(result["counts"]["stage_eligible_review_only"], 0)
        with self.assertRaisesRegex(RuntimeError, "handoff_source_count_changed"):
            audit_counts(rows[:-1], [], set(), {"nl": set(), "en": set()}, {"nl": True, "en": True})


if __name__ == "__main__":
    unittest.main()
