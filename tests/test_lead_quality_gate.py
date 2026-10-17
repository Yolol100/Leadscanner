import copy
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lead_quality_gate as q


def valid():
    opt=q.OPT_OUT
    return {
      "draft":{"draft_id":"draft-0123456789abcdef0123456789abcdef","email":"info@voorbeeld.nl","source_url":"https://voorbeeld.nl/contact","subject":"Onderhoud voor uw tuin","body":"Goedendag,\n\nJullie bieden onderhoud van groene daken aan.\n\nIk kan een duidelijke uitleg van onderhoudsplannen voorstellen, aansluitend op het contactformulier.\n\nMag ik een voorbeeld sturen?\n\n"+opt+"\n\nGroet,\nAndrew"},
      "verification":{"company_identity":"confirmed","branch":"confirmed","email":"confirmed","email_source_excerpt":"Mail info@voorbeeld.nl","email_source_url":"https://voorbeeld.nl/contact","fact":"confirmed","fact_quote":"onderhoud van groene daken","fact_source_excerpt":"Wij bieden onderhoud van groene daken aan","fact_source_url":"https://voorbeeld.nl/diensten","checked_at":datetime.now(timezone.utc).isoformat(),"dedupe":"clear","claims_supported":True,"existing_features":["contactformulier"]},
      "proposal":{"feature":"maintenance-plans","adds_value":True,"why_relevant":"Bestaande dienst begrijpelijker maken en contact vereenvoudigen"},
      "rubric":{"source_accuracy":2,"activity_fit":1.5,"distinctive_opening":1.5,"added_value":2,"natural_tone":1,"subject_clarity":1,"formal_requirements":1}
    }


class TestQuality(unittest.TestCase):
    def test_positive(self):
        r=q.assess(valid())
        self.assertEqual(r["score_0_to_10"],10)
        self.assertTrue(r["eligible_for_private_draft"])
        self.assertTrue(r["not_send_ready"])

    def test_score_over_max_rejected(self):
        v=valid();v["rubric"]["added_value"]=3
        with self.assertRaises(ValueError):q.assess(v)

    def test_nan_rejected(self):
        v=valid();v["rubric"]["natural_tone"]=float("nan")
        with self.assertRaises(ValueError):q.assess(v)

    def test_unverified_email(self):
        v=valid();v["verification"]["email"]="unknown"
        r=q.assess(v)
        self.assertLessEqual(r["score_0_to_10"],3.5)
        self.assertFalse(r["eligible_for_private_draft"])

    def test_unconfirmed_business(self):
        v=valid();v["verification"]["company_identity"]="unknown"
        self.assertLessEqual(q.assess(v)["score_0_to_10"],3.5)

    def test_wrong_branch(self):
        v=valid();v["verification"]["branch"]="disputed"
        self.assertLessEqual(q.assess(v)["score_0_to_10"],4)

    def test_cross_domain(self):
        v=valid();v["draft"]["email"]="info@andere.nl";v["verification"]["email_source_excerpt"]="Mail info@andere.nl"
        self.assertIn("email_domain_association_unconfirmed",q.assess(v)["reasons"])

    def test_existing_booking(self):
        v=valid();v["proposal"]["feature"]="boekingssysteem";v["verification"]["existing_features"]=["online boeken"]
        self.assertIn("already_existing_or_missing_feature",q.assess(v)["reasons"])

    def test_generic_opening(self):
        v=valid();v["draft"]["body"]=v["draft"]["body"].replace("Jullie bieden onderhoud van groene daken aan.","Ik kwam jullie website tegen.")
        self.assertLessEqual(q.assess(v)["score_0_to_10"],7)

    def test_optout_missing(self):
        v=valid();v["draft"]["body"]=v["draft"]["body"].replace(q.OPT_OUT,"")
        self.assertEqual(q.assess(v)["score_0_to_10"],0)

    def test_more_than_one_question(self):
        v=valid();v["draft"]["body"]=v["draft"]["body"].replace("Mag ik een voorbeeld sturen?","Kan dit? Mag ik een voorbeeld sturen?")
        self.assertIn("commercial_cta_count_invalid",q.assess(v)["reasons"])

    def test_stale_source(self):
        v=valid();v["verification"]["checked_at"]="2025-01-01T00:00:00+00:00"
        self.assertIn("source_check_missing_or_stale",q.assess(v)["reasons"])

    def test_dedupe_not_clear(self):
        v=valid();v["verification"]["dedupe"]="optout"
        self.assertFalse(q.assess(v)["eligible_for_private_draft"])

    def test_stalled(self):
        self.assertTrue(q.improvement_stalled({"score_0_to_10":8},{"score_0_to_10":8.05},1))
        self.assertTrue(q.improvement_stalled({"score_0_to_10":8},{"score_0_to_10":9},2))

    def test_resume_and_drift(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"input.jsonl"; output=Path(d)/"result.jsonl"
            source.write_text(json.dumps(valid())+"\n")
            self.assertEqual(q.review_file(source,output)["reviewed"],1)
            self.assertEqual(q.review_file(source,output)["reviewed"],1)
            source.write_text(json.dumps({**valid(),"proposal":{"feature":"other","adds_value":True,"why_relevant":"same"}})+"\n")
            with self.assertRaisesRegex(RuntimeError,"drift"):q.review_file(source,output)

    def test_duplicate_batch(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"input.jsonl";output=Path(d)/"output.jsonl"
            source.write_text((json.dumps(valid())+"\n")*2)
            with self.assertRaisesRegex(ValueError,"duplicate"):q.review_file(source,output)


if __name__=="__main__":
    unittest.main()
