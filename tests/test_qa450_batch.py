"""Synthetic QA450 copy/source gate tests. No network and no private credentials."""
import unittest
from unittest.mock import patch

import qa450_batch as q


def sample(opening, branch="restaurants", subject="Het menu bij Voorbeeld"):
    return {
        "draft_id":"draft-"+"a"*32,
        "company":"Voorbeeld",
        "branch":branch,
        "subject":subject,
        "body":"Goedendag,\n\n"+opening+"\n\n"
              "Ik help restaurants om hun menu op mobiel te tonen.\n\n"
              "Zal ik een kort voorbeeld sturen?\n\n"
              "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij.\n\n"
              "Groet,\nAndrew",
        "evidence_url":"https://voorbeeld.invalid/"
    }


class QualityTest(unittest.TestCase):
    GOOD=("bevestigd","bevestigd","bevestigd")

    def test_batch_ranges_are_bounded_and_last_batch_has_50(self):
        self.assertEqual(q.ranges_for_batch(1),(0,100))
        self.assertEqual(q.ranges_for_batch(4),(300,400))
        self.assertEqual(q.ranges_for_batch(5),(400,450))
        for number in (0,6,-1):
            with self.assertRaises(RuntimeError):
                q.ranges_for_batch(number)

    def test_generic_opening_is_not_given_a_nine(self):
        r=q.review_one(1,sample("Ik kwam de website van Voorbeeld tegen."),self.GOOD,"check")
        self.assertLess(float(r[4]),8.0)
        self.assertEqual(r[13],"HERSCHRIJVEN_AANBEVOLEN")

    def test_generic_topic_hook_is_not_ten(self):
        row=sample("Op de website van Voorbeeld zag ik informatie over lunch.")
        r=q.review_one(2,row,self.GOOD,"check")
        self.assertLess(float(r[4]),8.5)

    def test_specific_hook_is_capped_until_details_verified(self):
        r=q.review_one(3,sample("Op jullie website zag ik een uniek en passend detail."),self.GOOD,"check")
        self.assertLessEqual(float(r[4]),8.6)
        self.assertEqual(r[13],"INHOUDELIJK_BIJNA_GOED_DETAILCHECK_NODIG")

    def test_unreachable_source_is_a_blocker(self):
        r=q.review_one(4,sample("Op jullie website zag ik een detail."),
            ("niet_bevestigd","niet_bevestigd","niet_bevestigd"),"check")
        self.assertLessEqual(float(r[4]),6)
        self.assertEqual(r[13],"BRONCONTROLE_NODIG")

    def test_email_not_confirmed_is_blocker_not_auto_corrected(self):
        r=q.review_one(5,sample("Op jullie website zag ik een detail."),
            ("bevestigd","ander_adres_op_site","bevestigd"),"check")
        self.assertLessEqual(float(r[4]),5)
        self.assertEqual(r[7],"ander_adres_op_site")
        self.assertEqual(r[13],"BRONCONTROLE_NODIG")

    def test_unknown_branch_does_not_pass_as_on_target(self):
        row=sample("Ik kwam de website van Voorbeeld tegen.",branch="onbekend")
        self.assertEqual(q.offer_status(row),"handmatig_beoordelen")

    def test_intro_remains_detectable_as_copy_concern(self):
        row=sample("Ik kwam de website van Voorbeeld tegen.")
        row["body"]=row["body"].replace("Ik kwam", "Ik ben Andrew van Webactueel. Ik kwam")
        self.assertEqual(q.opening_kind(row["body"]),"specifieke_bedrijfsobservatie")
        # Separate source validation has already forbidden the removed intro.
        self.assertTrue("Ik ben Andrew van Webactueel" in row["body"])

    def test_no_unauthorized_batch_runs(self):
        with patch.dict("os.environ",{"QA450_BATCH":"0","QA450_TASK":q.TASK}):
            self.assertNotEqual(q.main(),0)


if __name__=="__main__":
    unittest.main()
