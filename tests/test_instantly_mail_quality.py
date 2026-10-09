"""Privacy/quality audit does not publish an identifiable lead or raw copy."""
import unittest
from unittest.mock import patch
from instantly_mail_quality import mail_quality_audit
class Tests(unittest.TestCase):
    def test_aggregates_and_redacts_sensitive_copy(self):
        rows=[{"email":"private@company.example","payload":{
            "leadscanner_subject":"Een vraag over uw website","leadscanner_body":"Hallo, ik bekeek jullie website. Ik heb een idee en stuur graag een kort voorbeeld. Is dat interessant? Groet, Andrew van Webactueel. Geen interesse, laat het me weten.",
            "leadscanner_contact_basis":"review_required"}},
            {"email":"private2@company.example","payload":{
            "leadscanner_subject":"A question","leadscanner_body":"Hello, I saw your website and had an idea about the content. Would you like to see a short example? Best, Andrew from Webactueel. Not interested is fine."}}]
        with patch("instantly_mail_quality.read_imported_leads",return_value=("source123",rows)):
            out=mail_quality_audit(object())
        self.assertEqual(out["source_count"],2)
        self.assertEqual(out["documented_contact_basis_count"],0)
        self.assertFalse(out["writes"])
        self.assertNotIn("private@",str(out))
        self.assertNotIn("I saw your website",str(out))
    def test_missing_copy_and_unresolved_token_count(self):
        rows=[{"payload":{"leadscanner_subject":"Idea {{firstName}}",
             "leadscanner_body":"Hello, website {{company}}"}},
              {"payload":{"leadscanner_subject":"","leadscanner_body":""}}]
        with patch("instantly_mail_quality.read_imported_leads",return_value=("id",rows)):
            out=mail_quality_audit(object())
        self.assertEqual(out["complete_copy_count"],1)
        self.assertEqual(out["mail_review_flags"]["missing_subject_or_body"],1)
        self.assertEqual(out["mail_review_flags"]["unresolved_template_markers"],1)
if __name__=="__main__":
    unittest.main()
