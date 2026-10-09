"""No-network copy and template contract tests; retain original reviewed copy."""
import re
import unittest
from instantly_campaign_copy import campaign_steps, campaign_payload
from instantly_client import inspect_campaign_sequence

LANGS=["nl","en"]
class Tests(unittest.TestCase):
    def test_sequences_have_personalized_approved_first_mail_and_two_followups(self):
        for language in LANGS:
            steps=campaign_steps(language)
            self.assertEqual(len(steps),3)
            self.assertEqual(steps[0]["variants"],[{"subject":"{{leadscanner_subject}}","body":"{{leadscanner_body}}"}])
            self.assertEqual([s["delay"] for s in steps],[4,5,1])
            self.assertEqual([s["variants"][0]["subject"] for s in steps[1:]],["",""])
            for step in steps:
                self.assertEqual(step["type"],"email")
                self.assertFalse("http://" in step["variants"][0]["body"])
                self.assertFalse("https://" in step["variants"][0]["body"])
    def test_liquid_guard_and_fallback_for_missing_legacy_data(self):
        for language in LANGS:
            one,two=campaign_steps(language)[1:]
            body=one["variants"][0]["body"]
            self.assertIn("{% if leadscanner_observation and leadscanner_value_action %}",body)
            self.assertIn("{% else %}",body)
            self.assertIn("{% endif %}",body)
            self.assertEqual(body.count("{{leadscanner_observation}}"),1)
            self.assertEqual(body.count("{{leadscanner_value_action}}"),1)
            self.assertIn("{% if leadscanner_observation %}",two["variants"][0]["body"])
            self.assertIn("{% endif %}",two["variants"][0]["body"])
    def test_copy_quality_and_contact_handling(self):
        for lang in LANGS:
            steps=campaign_steps(lang)
            for i,step in enumerate(steps[1:]):
                body=step["variants"][0]["body"]
                assert re.search(r"(?i)Andrew",body)
                assert re.search(r"(?i)Webactueel",body)
                self.assertLess(len(body.split()),125)
                self.assertNotIn("€",body)
                self.assertNotIn("ROI",body)
            settings=campaign_payload(lang)
            self.assertEqual(settings["email_list"],[])
            self.assertTrue(settings["stop_on_reply"])
            self.assertFalse(settings["open_tracking"])
    def test_actual_sequence_inspector_accepts_supported_fields(self):
        for lang in LANGS:
            campaign={"id":"example","status":0,"sequences":[{"steps":campaign_steps(lang)}]}
            report=inspect_campaign_sequence(campaign)
            self.assertEqual(report["email_step_count"],3)
            self.assertFalse(report["unsupported_leadscanner_variables"])
            self.assertFalse(report["unresolved_template_variables"])
            self.assertEqual(report["decision"],"reviewed_mail_copy_still_required")

if __name__=="__main__":
    unittest.main()
