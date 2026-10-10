"""Privacy/quality audit does not publish an identifiable lead or raw copy."""
import unittest
from unittest.mock import patch
from instantly_mail_quality import mail_quality_audit, classify_signature_tail
class Tests(unittest.TestCase):
    def test_aggregates_and_redacts_sensitive_copy(self):
        rows=[{"email":"private@company.example","payload":{
            "leadscanner_subject":"Een vraag over uw website","leadscanner_body":"Hallo, ik bekeek jullie website. Ik heb een idee en stuur graag een kort voorbeeld. Is dat interessant? Groet, Andrew Baeten. Geen interesse, laat het me weten.",
            "leadscanner_contact_basis":"review_required"}},
            {"email":"private2@company.example","payload":{
            "leadscanner_subject":"A question","leadscanner_body":"Hello, I saw your website and had an idea about the content. Would you like to see a short example? Best, Andrew Baeten. Not interested is fine."}}]
        with patch("instantly_mail_quality.read_imported_leads",return_value=("source123",rows)):
            out=mail_quality_audit(object())
        self.assertEqual(out["source_count"],2)
        self.assertEqual(out["documented_contact_basis_count"],0)
        self.assertEqual(out["mail_review_flags"]["legacy_brand_in_copy"],0)
        self.assertEqual(out["mail_review_flags"]["missing_andrew_baeten_signature"],0)
        self.assertEqual(out["mail_review_flags"]["missing_verified_followup_fields"],2)
        self.assertEqual(out["question_count_distribution"]["one"],2)
        self.assertEqual(sum(out["question_count_distribution"].values()),2)
        self.assertFalse(out["writes"])
        self.assertNotIn("private@",str(out))
        self.assertNotIn("I saw your website",str(out))
    def test_signature_tail_classification_is_strict_and_private(self):
        examples={
            "Hi, I noticed the quote page. Best,\\nAndrew": "unrecognized_tail",
            "Hoi, bedankt.\\n\\nGroet,\\nAndrew": "first_name_only_tail",
            "Hi there.\\n\\nBest,\\nAndrew": "first_name_only_tail",
            "Hoi.\\n\\nGroet,\\nAndrew Baeten": "full_name_tail",
            "Hoi.\\nGroet,": "closing_without_name_tail",
            "Could this be Andrew?": "unrecognized_tail",
            "Hi.\\nBest,\\nAndrew van Example": "unrecognized_tail",
        }
        for value, expected in examples.items():
            with self.subTest(tail=expected):
                self.assertEqual(classify_signature_tail(value.replace(chr(92)+"n", chr(10))), expected)

    def test_signature_counts_do_not_reveal_content_or_overwrite_any_leads(self):
        leads=[{"email":"hidden@firm.example","campaign":None,"payload":{
            "leadscanner_subject":"Een vraag over jullie website",
            "leadscanner_body":"Hoi, ik heb een concreet idee.\\n\\nGroet,\\nAndrew"}},
            {"email":"hidden2@firm.example","campaign":None,"payload":{
            "leadscanner_subject":"Website vraag",
            "leadscanner_body":"Hoi, ik heb een vraag.\\n\\nGroet,\\nAndrew Baeten"}}]
        for row in leads:
            row["payload"]["leadscanner_body"] = row["payload"]["leadscanner_body"].replace(chr(92)+"n", chr(10))
        with patch("instantly_mail_quality.read_imported_leads",return_value=("source",leads)):
            out=mail_quality_audit(object())
        self.assertEqual(out["signature_tail_distribution"]["first_name_only_tail"],1)
        self.assertEqual(out["signature_tail_distribution"]["full_name_tail"],1)
        self.assertEqual(out["source_leads_assigned_to_campaign"],0)
        self.assertFalse(out["writes"])
        self.assertNotIn("hidden@firm.example",str(out))
        self.assertNotIn("Hoi, ik heb",str(out))

    def test_legacy_brand_is_counted_without_exposing_recipient_copy(self):
        old_brand="Web"+"actueel"
        item={"email":"private@example.org","payload":{
            "leadscanner_subject":"Vraag over website",
            "leadscanner_body":"Hoi, dit gaat over je site. Groet, Andrew van "+old_brand,
        }}
        with patch("instantly_mail_quality.read_imported_leads",return_value=("safe-list",[item])):
            result=mail_quality_audit(object())
        self.assertEqual(result["mail_review_flags"]["legacy_brand_in_copy"],1)
        self.assertEqual(result["mail_review_flags"]["missing_andrew_baeten_signature"],1)
        self.assertNotIn("private@example.org",str(result))

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
