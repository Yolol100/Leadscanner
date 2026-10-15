"""Synthetic final-scope supplementation tests. No network or mailbox."""
import copy
import unittest
from unittest.mock import Mock, patch

import review450 as b
import review450_supplement as s
from test_review450_finalcopy import row


class SupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=[row(i) for i in range(450)]

    def test_organization_level_outliers_are_excluded(self):
        self.assertFalse(s.scope_allowed({"company":"Carlton Fictief","website":"https://example.net/"}))
        self.assertFalse(s.scope_allowed({"company":"Sportcentrum Fictief","website":"https://sportbedrijf-fictief.example.net/"}))
        self.assertTrue(s.scope_allowed({"company":"Fictief Schildersbedrijf","website":"https://example.net/"}))

    def test_private_excluded_domain_and_subdomain_blocked(self):
        value=row()
        domain=value["website"].split("/")[2]
        self.assertFalse(s.scope_allowed(value,{domain}))
        value["website"]="https://sub."+domain+"/"
        self.assertFalse(s.scope_allowed(value,{domain}))

    def test_preliminary_cross_domain_recipient_not_trusted_as_user_seed(self):
        value=row()
        value["email"]="info@different.example.org"
        value["origin"]="reverified"
        self.assertFalse(s.scope_allowed(value))
        value["origin"]="review50_reverified_v3"
        self.assertTrue(s.scope_allowed(value))

    def test_missing_private_scope_state_is_not_treated_as_empty(self):
        with patch.object(b,"read",return_value=[]):
            with self.assertRaisesRegex(RuntimeError,"unavailable"):
                s.private_exclusions(Mock())

    def test_incomplete_table_stops_without_any_public_request(self):
        with patch.object(b,"load_rows",return_value=self.rows[:-1]), \
             patch.object(b,"read",return_value=[["status","collecting"]]), \
             patch("review450_strict.inspect") as inspect:
            with self.assertRaisesRegex(RuntimeError,"unchanged_batch"):
                s.supplement(Mock())
        inspect.assert_not_called()

    def test_no_outliers_means_no_new_search_or_write(self):
        vals=[b.COLS]+[[r[k] for k in b.COLS] for r in self.rows]
        state=[["status","ready_for_review"],["content_sha256",b.digest(vals)]]
        with patch.object(b,"load_rows",return_value=self.rows), \
             patch.object(b,"read",return_value=state), \
             patch.object(s,"private_exclusions",return_value=set()), \
             patch("review450_strict.persist") as persist, \
             patch("review450_strict.inspect") as inspect:
            result=s.supplement(Mock())
        self.assertEqual(result,{"excluded":0,"replacements":0,"prepared":450})
        persist.assert_not_called()
        inspect.assert_not_called()

    def test_one_scope_outlier_replaced_only_after_verified_distinct_source(self):
        current=copy.deepcopy(self.rows)
        current[0]["company"]="Carlton Fictief"
        new=row(900)
        expected=current[1:]+[new]
        vals=[b.COLS]+[[r[k] for k in b.COLS] for r in current]
        state=[["status","ready_for_review"],["content_sha256",b.digest(vals)],
               ["sites_checked","500"],["regions","2"]]
        seeds=[s.HEADERS,["Fictief Bedrijf 900","https://fictief-900.example.net/","painter","NL","3011 AA"]]
        def read(_conn,_sid,a1):
            return state if a1.startswith(b.STATE) else seeds
        with patch.object(b,"load_rows",side_effect=[current,current,expected]), \
             patch.object(b,"read",side_effect=read), \
             patch.object(s,"private_exclusions",return_value=set()), \
             patch("registry_readonly.load_suppressions",return_value=[]), \
             patch("registry_readonly.load_discovery_suppressions",return_value=[]), \
             patch("review450_strict.inspect",return_value=new) as inspect, \
             patch("review450_strict.persist") as persist:
            result=s.supplement(Mock())
        self.assertEqual(result,{"excluded":1,"replacements":1,"prepared":450})
        self.assertEqual(inspect.call_count,1)
        persist.assert_called_once()
        self.assertEqual(persist.call_args.args[1],expected)
        self.assertEqual(persist.call_args.args[2],"ready_for_review")
        b.unique(expected)


if __name__=="__main__":
    unittest.main()
