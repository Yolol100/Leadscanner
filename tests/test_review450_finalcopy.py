"""No-network editorial and batch QA tests with fictional public-site data."""
import copy
import unittest
from unittest.mock import patch

import review450 as b
import review450_strict as s
import review450_finalcopy as f
from test_review450 import item


def row(number=0, cluster=1, branch="schilders", text="schilder houtrotherstel"):
    source="https://fictief-{}.example.net/".format(number)
    data=item(cluster,branch,"Fictief Bedrijf {}".format(number),source)
    return s.render(data,[(source,text+" 3011 AA Rotterdam")],"discovery_nl_checked")


class FinalCopyTests(unittest.TestCase):
    def test_six_groups_have_one_business_question_and_no_intro(self):
        cases=[(1,"schilders","schilder houtrotherstel"),(2,"kappers","kapper highlights"),
               (3,"restaurants","restaurant lunch"),(4,"garages","garage apk"),
               (5,"fysiotherapiepraktijken","fysiotherapie handtherapie"),
               (6,"reparatiebedrijven","fietsreparatie reparatie")]
        for i,(cluster,branch,text) in enumerate(cases):
            with self.subTest(cluster=cluster):
                old=row(i,cluster,branch,text)
                new=f.polish(old)
                b.validate(new)
                self.assertNotIn(b.FORBIDDEN,new["body"])
                self.assertEqual(new["body"].count("?"),2)
                self.assertEqual(new["body"].count(b.OPT),1)
                self.assertLessEqual(len(new["body"].split()),110)
                for key in ("draft_id","company","email","source_url","website","evidence"):
                    self.assertEqual(new[key],old[key])

    def test_literal_evidence_is_mandatory_for_generated_copy(self):
        value=row()
        value["evidence"]="unverified allegation"
        with self.assertRaisesRegex(RuntimeError,"source_proof"):
            f.polish(value)

    def test_individually_reviewed_copy_is_not_replaced_by_template(self):
        value=row()
        value["origin"]="review50_reverified_v3"
        previous=copy.deepcopy(value)
        self.assertEqual(f.polish(value),previous)

    def test_complete_450_are_all_validated_and_unique(self):
        values=[f.polish(row(i)) for i in range(450)]
        result=f.audit(values)
        self.assertEqual(result["count"],450)
        self.assertEqual(result["unique_subjects"],450)
        self.assertEqual(result["unique_bodies"],450)
        self.assertEqual(result["sent"],0)
        self.assertEqual(result["mailbox_writes"],0)
        self.assertEqual(result["clusters"],{"1":450})
        self.assertLessEqual(result["max_words"],110)

    def test_449_never_pass_final_review(self):
        with self.assertRaisesRegex(RuntimeError,"exactly_450"):
            f.audit([row(i) for i in range(449)])

    def test_chain_is_never_polished_for_approval(self):
        value=row()
        value["company"]="Holiday Inn Fictief"
        with self.assertRaisesRegex(RuntimeError,"chain"):
            f.polish(value)

    def test_new_footer_provider_address_cannot_pass_audit(self):
        values=[f.polish(row(i)) for i in range(450)]
        values[10]["email"]="info@different-provider.example.org"
        with self.assertRaisesRegex(RuntimeError,"domain"):
            f.audit(values)

    def test_generic_category_does_not_repeat_restaurant_as_fake_specific_detail(self):
        value=f.polish(row(1,3,"restaurants","restaurant"))
        self.assertIn("Ik kwam de website van",value["body"])
        self.assertNotIn("las ik over het restaurant",value["body"])
        self.assertIn("menu",value["body"])


if __name__=="__main__":
    unittest.main()
