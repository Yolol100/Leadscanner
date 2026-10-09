"""No-network tests for exact language classification and provider-safe audit."""
import unittest
from unittest.mock import patch

from instantly_language_campaigns import (
    LANGUAGE_CAMPAIGN_NAMES, audit_language_split, classify_language,
    inspect_lead_language, read_imported_leads,
)


class Provider:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_leads(self, **kwargs):
        self.calls.append(kwargs)
        return {"items": self.rows, "next_starting_after": None}


class LanguageCampaignTests(unittest.TestCase):
    def test_dutch_personalized_draft(self):
        subject = "Een korte vraag over jullie website"
        body = "Hoi, ik zag jullie website en dacht aan een klein idee voor de pagina. Als je wilt, stuur ik graag een concreet voorstel. Laat gerust weten."
        self.assertEqual(classify_language(subject, body), "nl")

    def test_english_personalized_draft(self):
        subject = "Quick question about your website"
        body = "Hi, I noticed your website and thought of an idea. Would you like me to send a short example? Let me know if you're interested. Best regards."
        self.assertEqual(classify_language(subject, body), "en")

    def test_ambiguous_is_held(self):
        self.assertEqual(classify_language("Website", "Hello, website design."), "unknown")
        self.assertEqual(classify_language("Website", "Hoi, website design."), "unknown")
        self.assertEqual(classify_language("Jouw website", "Hi, I saw your website and I had a thought. Ik zag een idee, dus laat weten als dit past."), "unknown")

    def test_missing_basis_blocks_routing(self):
        lead = {"email":"unit@example.org","campaign":None,"payload":{"leadscanner_import_origin":"myhost_drafts","leadscanner_subject":"Hoi","leadscanner_body":"Hallo"}}
        self.assertEqual(inspect_lead_language(lead), "missing_data")

    def test_assigned_and_suppressed_excluded(self):
        self.assertEqual(inspect_lead_language({"campaign":"existing_campaign"}), "already_assigned")
        self.assertEqual(inspect_lead_language({"status":-2,"campaign":None}), "suppressed")

    def test_audit_counts_without_lead_copy(self):
        source="test-list-id"
        nl = {"id":"1","email":"nl@example.org","list_id":source,"campaign":None,
              "payload":{"leadscanner_import_origin":"myhost_drafts","leadscanner_contact_basis":"review_required",
              "leadscanner_subject":"Een korte vraag over jullie website","leadscanner_body":"Hoi, ik zag jullie website en dacht aan een klein idee. Laat gerust weten als je graag een voorstel wilt."}}
        en = {"id":"2","email":"en@example.org","list_id":source,"campaign":None,
              "payload":{"leadscanner_import_origin":"myhost_drafts","leadscanner_contact_basis":"review_required",
              "leadscanner_subject":"Quick question about your website","leadscanner_body":"Hi, I noticed your website and thought of an idea. Would you like me to send a short example? Best regards."}}
        unknown = {"id":"3","email":"unknown@example.org","list_id":source,"campaign":None,
                   "payload":{"leadscanner_import_origin":"myhost_drafts","leadscanner_contact_basis":"review_required",
                   "leadscanner_subject":"Website","leadscanner_body":"Hi"}}
        api=Provider([nl,en,unknown])
        with patch("instantly_language_campaigns.matching_list_ids",return_value=[source]):
            audit=audit_language_split(api)
        self.assertEqual((audit["nl"],audit["en"],audit["unknown_hold"]),(1,1,1))
        self.assertEqual(audit["source_count"],3)
        self.assertFalse(audit["write"])
        self.assertFalse(audit["automatic_send"])
        self.assertNotIn("nl@example.org",str(audit))
        self.assertEqual(len(LANGUAGE_CAMPAIGN_NAMES),2)

    def test_missing_list_fails_closed(self):
        with patch("instantly_language_campaigns.matching_list_ids",return_value=[]):
            with self.assertRaisesRegex(RuntimeError,"single_import_source_list_required"):
                read_imported_leads(Provider([]))

    def test_mismatched_list_fails_closed(self):
        with patch("instantly_language_campaigns.matching_list_ids",return_value=["correct"]):
            with self.assertRaisesRegex(RuntimeError,"language_source_list_identity_mismatch"):
                read_imported_leads(Provider([{"id":"id","email":"person@example.org","list_id":"wrong"}]))


    def test_duplicate_source_email_blocks_routing_before_any_write(self):
        rows=[{"id":str(i),"email":"same@example.org","list_id":"correct"} for i in (1,2)]
        api=Provider(rows)
        with patch("instantly_language_campaigns.matching_list_ids",return_value=["correct"]):
            with self.assertRaisesRegex(RuntimeError,"language_source_duplicate_or_missing_email"):
                read_imported_leads(api)


if __name__=="__main__":
    unittest.main()
