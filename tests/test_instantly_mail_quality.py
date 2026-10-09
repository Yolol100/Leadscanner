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
        self.assertEqual(out["question_count_distribution"]["one"],2)
        self.assertEqual(sum(out["question_count_distribution"].values()),2)
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
    def test_question_distribution_and_no_personal_copy_leak(self):
        bodies=[
            "Hello there. No question in this brief reviewed text. Best, Andrew.",
            "Hi, could I share something? Best, Andrew.",
            "Hi, does this fit? Would that help? Best, Andrew.",
            "Hi, first? second? third? Best, Andrew.",
        ]
        rows=[{"payload":{
            "leadscanner_subject":"Contact over de website",
            "leadscanner_body":body,
        }} for body in bodies]
        with patch("instantly_mail_quality.read_imported_leads",
                   return_value=("source",rows)):
            audit=mail_quality_audit(object())
        self.assertEqual(audit["question_count_distribution"],
                         {"zero":1,"one":1,"two":1,"three_or_more":1})
        self.assertEqual(audit["mail_review_flags"]["not_exactly_one_question"],3)
        self.assertTrue(audit["question_count_is_a_review_heuristic_not_reply_rate"])
        for body in bodies:
            self.assertNotIn(body,str(audit))

if __name__=="__main__":
    unittest.main()
