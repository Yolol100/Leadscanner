"""Synthetic scope and copy regression tests: no real companies or network."""
import unittest
from unittest.mock import Mock, patch

import review450 as b
import review450_strict as s
from test_review450 import item


class ScopeTests(unittest.TestCase):
    def test_country_must_be_explicitly_netherlands(self):
        hint={"name_hint":"Fictief Schildersbedrijf","website_hint":"https://example.net/","category_hint":"painter"}
        for country in ("BE","DE","",None):
            self.assertFalse(s.allowed_hint(dict(hint,country_hint=country)))
        self.assertTrue(s.allowed_hint(dict(hint,country_hint="NL")))

    def test_chain_without_independent_decision_proof_is_excluded(self):
        for name in ("Amrath Hotel Fictief","Holiday Inn Fictief","Best Western Fictief","Basic-Fit Fictief"):
            self.assertTrue(s.chain(name))
        self.assertFalse(s.chain("Fictief Hoveniersbedrijf"))

    def test_foreign_or_missing_official_postcode_fails(self):
        self.assertFalse(s.local_proof([("https://example.net/","12345 Berlin")],{"country_hint":"NL"}))
        self.assertFalse(s.local_proof([("https://example.net/","3011 AA Rotterdam")],{"country_hint":"BE"}))
        self.assertFalse(s.local_proof([("https://example.net/","3011 AA Rotterdam")],{"country_hint":"NL","postcode_hint":"3511 AA"}))
        self.assertTrue(s.local_proof([("https://example.net/","Adres 3011 AA Rotterdam")],{"country_hint":"NL","postcode_hint":"3011AA"}))

    def test_service_term_not_substring_or_negation(self):
        self.assertFalse(s.term_match("Bloemen voor vrouwen","rouw"))
        self.assertFalse(s.term_match("Geen rouwboeketten beschikbaar","rouw"))
        self.assertTrue(s.term_match("Wij maken rouwboeketten","rouw"))
        self.assertTrue(s.term_match("Gevelreiniging is een dienst","gevelreiniging"))

    def test_known_chain_never_causes_web_request(self):
        with patch.object(b,"Capture") as capture:
            self.assertIsNone(s.inspect({"name_hint":"Amrath Hotel Fictief","website_hint":"https://example.net/"},"test"))
        capture.assert_not_called()


class RefinedCopyTests(unittest.TestCase):
    def test_hairdresser_copy_no_generic_lessons_offer(self):
        row=s.render(item(2,"kappers"),[("https://example.net/","Fictief kapsalon kleuren 3011 AA")],"test")
        self.assertNotIn("lessen",row["body"])
        self.assertNotIn(b.FORBIDDEN,row["body"])
        self.assertIn("kleurbehandelingen",row["body"])
        b.validate(row)

    def test_original_review_copy_is_retained_for_exact_reverified_email(self):
        previous=[""]*15
        previous[4]="info@example.net"
        previous[8]="Bestaand goedgekeurd onderwerp"
        previous[9]="Goedendag,\n\nIk ben Andrew van Webactueel. Ik help schilders met duidelijke voorbeelden bij het aanvragen van schilderwerk. Zo ziet een bezoeker welke gegevens handig zijn voordat er persoonlijk contact is.\n\nZal ik een kort voorbeeld sturen?\n\n"+b.OPT+"\n\nGroet,\nAndrew"
        previous[13]="REVIEW"
        row=s.render(item(),[("https://example.net/","schilder houtrotherstel 3011 AA")],"test",previous)
        self.assertEqual(row["subject"],previous[8])
        self.assertEqual(row["body"],previous[9].replace(b.FORBIDDEN+". ",""))
        self.assertEqual(row["origin"],"review50_reverified_v3")
        previous[4]="other@example.net"
        with self.assertRaises(RuntimeError):
            s.render(item(),[("https://example.net/","schilder houtrotherstel 3011 AA")],"test",previous)

    def test_cafe_fallback_does_not_say_jullie_twice(self):
        row=s.render(item(3,"horecazaken"),[("https://example.net/","Fictief cafe 3011 AA")],"test")
        self.assertNotIn("jullie horecazaak",row["body"])
        self.assertIn("het cafe",row["body"])

    def test_missing_source_term_stops_copy(self):
        with self.assertRaisesRegex(RuntimeError,"literal"):
            s.render(item(),[("https://example.net/","irrelevant 3011 AA")],"test")

    def test_rejected_previous_rows_cleared_atomically_with_new_state(self):
        calls=[]
        def original_post(_conn,requests):
            calls.append(requests)
        def state(conn,rows,phase,checked,regions):
            b.post(conn,[{"updateCells":{"rows":b.cells([b.COLS]),"fields":"userEnteredValue"}}])
        with patch.object(b,"post",side_effect=original_post),patch.object(b,"state",side_effect=state):
            s.persist(Mock(),[],"collecting_strict",0,0)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(calls[0]),2)
        clear=calls[0][1]["updateCells"]
        self.assertEqual(clear["range"]["sheetId"],b.TAB_ID)
        self.assertEqual(clear["range"]["startRowIndex"],1)
        self.assertEqual(clear["range"]["endRowIndex"],451)
        self.assertEqual(clear["fields"],"userEnteredValue")


if __name__=="__main__":
    unittest.main()
