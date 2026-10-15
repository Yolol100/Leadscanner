"""No-network checks of evidence-only rewrite and private QA phase gates."""
import unittest
from unittest.mock import patch
import improve450_copy as c
import improve450_runner as q
import review450 as b


class CopyQuality(unittest.TestCase):
    def row(self):
        return {
            "draft_id":"draft-"+"a"*32,
            "created_at":"2026-10-15T17:00:00+00:00",
            "company":"Testrestaurant Voorbeeld",
            "email":"info@voorbeeld.invalid",
            "source_url":"https://voorbeeld.invalid/contact/",
            "subject":"Lunch bij Testrestaurant Voorbeeld",
            "body":"Goedendag,\n\nJullie website noemt lunch.\n\nIk kan een voorbeeld maken.\n\n"
                  "Mag ik een kort voorbeeld sturen?\n\n"+b.OPT+"\n\nGroet,\nAndrew",
            "website":"https://voorbeeld.invalid/",
            "cluster":"3",
            "branch":"restaurants",
            "evidence_url":"https://voorbeeld.invalid/",
            "evidence":"Letterlijke dienstterm: restaurant; Nederlandse postcode op de officiele site bevestigd.",
            "origin":"reverified",
            "qa_status":"verified_website_email_copy",
            "run_id":"123456",
            "task":b.TASK,
        }

    def test_source_specific_two_features(self):
        row=self.row()
        features,rank=c.topics_from_verified_pages(row,[
            ("https://voorbeeld.invalid/","Restaurant: Onze rijsttafels, afhalen en sushi staan op het menu.")])
        self.assertEqual(features[:2],["rijsttafels","sushi"])
        self.assertEqual(rank,2)

    def test_never_infer_feature_from_another_word(self):
        self.assertFalse(c.topic_pattern("vis").search("advies bij de klant"))
        self.assertTrue(c.topic_pattern("sushi").search("sushi arrangementen"))

    def test_copy_preserves_disclaimer_one_cta_and_signoff(self):
        s,body,status,score,_=c.rewrite(self.row(),[],["rijsttafels","sushi"],2)
        self.assertEqual(status,"VOORSTEL_BRONVERMELD")
        self.assertLess(score,10)
        self.assertEqual(body.count("?"),2)
        self.assertEqual(body.count(b.OPT),1)
        self.assertNotIn("Ik ben Andrew van Webactueel",body)
        self.assertIn("Testrestaurant Voorbeeld",body)
        self.assertLessEqual(len(body.split()),110)
        self.assertTrue(body.endswith("Groet,\nAndrew"))
        self.assertIn("rijsttafels",s)

    def test_unverified_evidence_never_generates_claim(self):
        row=self.row()
        with patch.object(c,"capture_official",return_value=([],"","BRON_OF_ADRES_NIET_BEVESTIGD")):
            result=c.evaluate(1,row,["1",row["draft_id"]]+[""]*14)
        self.assertFalse(result[8])
        self.assertFalse(result[9])
        self.assertIn("NIET_BEVESTIGD",result[12])

    def test_good_human_reviewed_original_is_preserved(self):
        row=self.row()
        row["origin"]="review50_reverified_v3"
        qa=["1",row["draft_id"]]+[""]*11+["INHOUDELIJK_BIJNA_GOED_DETAILCHECK_NODIG"]+[""]*2
        qa[4]="8.6"
        with patch.object(c,"capture_official",return_value=([("https://voorbeeld.invalid/","lunch")],
                                                              "https://voorbeeld.invalid/",
                                                              "BRON_EN_ADRES_BEVESTIGD")):
            result=c.evaluate(1,row,qa)
        self.assertEqual(result[9],row["body"])
        self.assertEqual(result[12],"BESTAANDE_STERKE_TEKST_BEHOUDEN")

    def test_safe_domain_root_only_no_third_party_redirect(self):
        urls=c.candidate_urls(self.row())
        self.assertTrue(all("voorbeeld.invalid" in u for u in urls))
        self.assertLessEqual(len(urls),3)

    def test_all_five_phase_boundaries(self):
        self.assertEqual(q.limits(1),(0,100))
        self.assertEqual(q.limits(4),(300,400))
        self.assertEqual(q.limits(5),(400,450))
        for invalid in (0,6,-1):
            with self.assertRaises(RuntimeError):
                q.limits(invalid)

    def test_no_task_env_blocks(self):
        with patch.dict("os.environ",{"IMPROVE450_TASK":"wrong"}):
            self.assertEqual(q.main(),1)


if __name__=="__main__":
    unittest.main()
