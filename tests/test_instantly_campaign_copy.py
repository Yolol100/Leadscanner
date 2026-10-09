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
            self.assertEqual([s["delay"] for s in steps],[4,5,0])
            self.assertEqual([s["variants"][0]["subject"] for s in steps[1:]],["",""])
            for step in steps:
                self.assertEqual(step["type"],"email")
                self.assertFalse("http://" in step["variants"][0]["body"])
                self.assertFalse("https://" in step["variants"][0]["body"])
    def test_step_delays_mean_wait_before_the_following_email(self):
        # Instantly official July 2026 article: 0 on a non-terminal step
        # would trigger an immediate follow-up. Both gaps must be >=1 day.
        for language in ("nl","en"):
            steps = campaign_steps(language)
            self.assertEqual(steps[0]["delay"],4)
            self.assertEqual(steps[1]["delay"],5)
            self.assertGreater(steps[0]["delay"],0)
            self.assertGreater(steps[1]["delay"],0)
            self.assertEqual(steps[2]["delay"],0)

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
    def test_auto_route_by_reviewed_text_only(self):
        from instantly_campaign_copy import AUTO_CAMPAIGN_ID,TARGET_CAMPAIGNS,resolve_language_destination
        class Provider:
            def get_campaign(self,cid):
                lang=next(k for k,v in TARGET_CAMPAIGNS.items() if v[0]==cid)
                return {"id":cid,"name":TARGET_CAMPAIGNS[lang][1],"status":0,
                        "email_list":[],"sequences":[{"steps":campaign_steps(lang)}]}
        examples={
          "nl":("Een korte vraag over jullie website","Hoi, ik zag jullie website en dacht aan een klein idee voor de pagina. Als je wilt, stuur ik graag een concreet voorstel. Laat gerust weten."),
          "en":("Quick question about your website","Hi, I noticed your website and thought of an idea. Would you like me to send a short example? Let me know if you're interested. Best regards.")
        }
        for language,(subject,body) in examples.items():
            row={"status":"review_draft","review_mode":"reviewed_mail","subject":subject,"body":body}
            self.assertEqual(resolve_language_destination(Provider(),row,AUTO_CAMPAIGN_ID),TARGET_CAMPAIGNS[language][0])
            wrong="nl" if language=="en" else "en"
            with self.assertRaisesRegex(ValueError,"reviewed_mail_campaign_language_mismatch"):
                resolve_language_destination(Provider(),row,TARGET_CAMPAIGNS[wrong][0])
        with self.assertRaisesRegex(ValueError,"reviewed_mail_language_ambiguous_hold"):
            resolve_language_destination(Provider(),{"status":"review_draft","subject":"Website","body":"Hi"},AUTO_CAMPAIGN_ID)
        with self.assertRaisesRegex(ValueError,"auto_language_requires_reviewed_mail"):
            resolve_language_destination(Provider(),{"status":"sequence_facts_review","review_mode":"instantly_sequence"},AUTO_CAMPAIGN_ID)

    def test_auto_route_never_uses_campaign_with_senders(self):
        from instantly_campaign_copy import AUTO_CAMPAIGN_ID,TARGET_CAMPAIGNS,resolve_language_destination
        class Unsafe:
            def get_campaign(self,cid):
                return {"id":cid,"name":TARGET_CAMPAIGNS["nl"][1],"status":0,
                        "email_list":["sender@example.org"],"sequences":[{"steps":campaign_steps("nl")}]}
        row={"status":"review_draft","subject":"Een korte vraag over jullie website",
             "body":"Hoi, ik zag jullie website en dacht aan een klein idee voor de pagina. Als je wilt, stuur ik graag een concreet voorstel. Laat gerust weten."}
        with self.assertRaisesRegex(ValueError,"auto_language_requires_zero_senders"):
            resolve_language_destination(Unsafe(),row,AUTO_CAMPAIGN_ID)

    def test_fact_cta_avoids_repeated_example_phrases(self):
        nl=campaign_steps("nl")[1]["variants"][0]["body"]
        en=campaign_steps("en")[1]["variants"][0]["body"]
        self.assertIn("maken, zodat je ziet wat ik bedoel",nl)
        self.assertIn("prepare {{leadscanner_value_action}} to make the idea tangible",en)
        self.assertNotIn("als kort voorbeeld",nl)
        self.assertNotIn("as a short example",en)

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
            self.assertTrue(settings["insert_unsubscribe_header"])
            self.assertNotIn("Geen interesse?",steps[1]["variants"][0]["body"])
    def test_actual_sequence_inspector_accepts_supported_fields(self):
        for lang in LANGS:
            campaign={"id":"example","status":0,"sequences":[{"steps":campaign_steps(lang)}]}
            report=inspect_campaign_sequence(campaign)
            self.assertEqual(report["email_step_count"],3)
            self.assertFalse(report["unsupported_leadscanner_variables"])
            self.assertFalse(report["unresolved_template_variables"])
            self.assertEqual(report["decision"],"reviewed_mail_copy_still_required")


    def test_auto_route_rejects_unapproved_followup_content_drift(self):
        from instantly_campaign_copy import AUTO_CAMPAIGN_ID,TARGET_CAMPAIGNS,resolve_language_destination
        class Drifted:
            def get_campaign(self,cid):
                steps=campaign_steps("nl")
                steps[1]["variants"][0]["body"] += " Unreviewed extra claim."
                return {"id":cid,"name":TARGET_CAMPAIGNS["nl"][1],
                        "status":0,"email_list":[],"sequences":[{"steps":steps}]}
        row={"status":"review_draft","review_mode":"reviewed_mail",
             "subject":"Een korte vraag over jullie website",
             "body":"Hoi, ik zag jullie website en dacht aan een klein idee voor de pagina. Als je wilt, stuur ik graag een concreet voorstel. Laat gerust weten."}
        with self.assertRaisesRegex(ValueError,"auto_language_copy_readback_mismatch"):
            resolve_language_destination(Drifted(),row,AUTO_CAMPAIGN_ID)

if __name__=="__main__":
    unittest.main()
