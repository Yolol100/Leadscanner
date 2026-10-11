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
    def test_site_candidate_aggregate_counts_rewrites_without_exposing_copy(self):
        obs="Bezoekers kunnen online een afspraak aanvragen voor onderhoud."
        action="een kort voorbeeld voor de afspraakroute"
        proposed=("Hoi, op jullie website staat: "+obs+" Hierbij kan ik "+action+
                  " uitwerken. Zal ik dat toesturen? Geen interesse: antwoord nee; "
                  "dan mail ik niet meer.\nGroet,\nAndrew Baeten")
        candidate={
            "leadscanner_site_research_status":"candidate_review_required",
            "leadscanner_site_candidate_source_type":"official_site",
            "leadscanner_site_candidate_observation":obs,
            "leadscanner_site_candidate_value_action":action,
            "leadscanner_site_candidate_evidence_url":"https://studio.example.org/afspraak",
            "leadscanner_site_candidate_contact_url":"https://studio.example.org/contact",
            "leadscanner_site_candidate_official_domain":"studio.example.org",
            "leadscanner_site_candidate_subject":"idee voor jullie afspraakroute",
            "leadscanner_site_candidate_body":proposed,
            "leadscanner_contact_basis":"review_required",
            "leadscanner_subject":"oud onderwerp",
            "leadscanner_body":"Oude eerste mail. Geen interesse. Groet, Andrew Baeten",
        }
        rows=[{"email":"first@studio.example.org","payload":dict(candidate)},
              {"email":"second@studio.example.org","payload":dict(candidate)},
              {"email":"third@studio.example.org","payload":{
                   "leadscanner_subject":"Other topic",
                   "leadscanner_body":"Hallo, tweede tekst. Groet, Andrew Baeten"}}]
        with patch("instantly_mail_quality.read_imported_leads",return_value=("isolated",rows)):
            report=mail_quality_audit(object())
        review=report["site_candidate_review"]
        self.assertEqual(review["present"],2)
        self.assertEqual(review["complete_review_candidate"],2)
        self.assertEqual(review["new_first_mail_candidate"],2)
        self.assertEqual(review["permission_still_unverified"],2)
        self.assertEqual(review["duplicate_mail_pairs"]["recipients_in_reused_groups"],2)
        self.assertEqual(review["reused_observations"]["reused_group_count"],1)
        self.assertEqual(sum(review["copy_quality_flags"].values()),0)
        self.assertFalse(review["raw_copy_or_fingerprints_returned"])
        for private in ("first@studio.example.org",obs,proposed,action):
            self.assertNotIn(private,str(report))
    def test_site_question_inside_evidence_is_not_an_extra_outreach_question(self):
        observation = "Kunnen bezoekers online een afspraak aanvragen?"
        action = "een korte voorbeeldvariant voor de afspraakroute"
        body = (
            'Hoi, op jullie website staat: "' + observation + '"\\n\\n'
            'Ik kan ' + action + ' schetsen. Zal ik dat sturen?\\n\\n'
            'Geen interesse: antwoord nee; dan mail ik niet meer.\\n\\n'
            'Groet,\\nAndrew Baeten'
        ).replace("\\\\n", "\\n")
        payload = {
            "leadscanner_site_research_status": "candidate_review_required",
            "leadscanner_site_candidate_observation": observation,
            "leadscanner_site_candidate_value_action": action,
            "leadscanner_site_candidate_source_type": "official_site",
            "leadscanner_site_candidate_evidence_url": "https://firma.example.org/afspraak",
            "leadscanner_site_candidate_contact_url": "https://firma.example.org/contact",
            "leadscanner_site_candidate_official_domain": "firma.example.org",
            "leadscanner_site_candidate_subject": "idee voor afspraakroute",
            "leadscanner_site_candidate_body": body,
            "leadscanner_subject": "oud",
            "leadscanner_body": "Oud concept. Geen interesse. Groet, Andrew Baeten",
            "leadscanner_contact_basis": "review_required",
        }
        self.assertEqual(body.count("?"), 2)
        with patch("instantly_mail_quality.read_imported_leads", return_value=("list", [{"payload": payload}])):
            report = mail_quality_audit(object())
        review = report["site_candidate_review"]
        self.assertEqual(review["complete_review_candidate"], 1)
        self.assertEqual(review["copy_quality_flags"]["not_one_primary_question"], 0)
        self.assertEqual(review["permission_still_unverified"], 1)
        self.assertNotIn(observation, str(report))

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

    def test_copy_diversity_only_returns_group_counts_not_pii_or_hashes(self):
        first = "Hi. A specific website note. Can I send a preview? Best,\nAndrew Baeten"
        second = "Hi. Another website note. Can I send a preview? Best,\nAndrew Baeten"
        third = "Hi. Third website note. Can I send a preview? Best,\nAndrew Baeten"
        rows = [
            {"email": "hidden1@example.org", "payload": {
                "leadscanner_subject": "Subject A",
                "leadscanner_body": first,
                "leadscanner_contact_basis": "review_required"}},
            {"email": "hidden2@example.org", "payload": {
                "leadscanner_subject": "Subject A ",
                "leadscanner_body": first.replace("  ", " "),
                "leadscanner_contact_basis": "review_required"}},
            {"email": "hidden3@example.org", "payload": {
                "leadscanner_subject": "Subject B",
                "leadscanner_body": second,
                "leadscanner_contact_basis": "review_required"}},
            {"email": "hidden4@example.org", "payload": {
                "leadscanner_subject": "Subject C",
                "leadscanner_body": third,
                "leadscanner_contact_basis": "review_required"}},
        ]
        with patch("instantly_mail_quality.read_imported_leads",return_value=("source",rows)):
            report=mail_quality_audit(object())
        self.assertEqual(report["copy_diversity"]["subject"]["distinct_count"],3)
        self.assertEqual(report["copy_diversity"]["body"]["distinct_count"],3)
        self.assertEqual(report["copy_diversity"]["subject_and_body_pair"]["distinct_count"],3)
        self.assertEqual(report["copy_diversity"]["body"]["recipients_in_reused_groups"],2)
        self.assertEqual(report["copy_diversity"]["body"]["largest_group_size"],2)
        self.assertTrue(report["copy_diversity"]["diversity_is_not_personalization_proof"])
        self.assertFalse(report["copy_diversity"]["raw_text_or_fingerprints_returned"])
        self.assertEqual(report["contact_basis_unverified_count"],4)
        for private in ("hidden1@example.org","Subject A","specific website note"):
            self.assertNotIn(private,str(report))
        self.assertFalse(report["writes"])

    def test_generic_interest_invitation_is_not_optout_evidence(self):
        messages=(
            ("nl","Hoi, laat het weten als je een voorbeeld wilt. Groet,\nAndrew Baeten",1),
            ("nl","Hoi, geen interesse is prima; dan stop ik. Groet,\nAndrew Baeten",0),
            ("en","Hello, let me know if this could help. Best,\nAndrew Baeten",1),
            ("en","Hello, if this isn't relevant just reply 'no' and I'll stop. Best,\nAndrew Baeten",0),
        )
        for language,body,expected in messages:
            with self.subTest(language=language,expected=expected):
                row={"email":"hidden@example.org","payload":{
                    "leadscanner_subject":"Question about a website","leadscanner_body":body}}
                with patch("instantly_mail_quality.read_imported_leads",return_value=("source",[row])), \
                     patch("instantly_mail_quality.classify_language",return_value=language):
                    report=mail_quality_audit(object())
                self.assertEqual(report["mail_review_flags"]["no_obvious_optout_phrase"],expected)
                self.assertEqual(report["language_review"][language]["no_obvious_optout_phrase"],expected)
                self.assertFalse(report["writes"])

if __name__=="__main__":
    unittest.main()
