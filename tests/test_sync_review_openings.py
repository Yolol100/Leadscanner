"""Synthetic safety tests; no private Sheet, network or IMAP access."""
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_review_openings as target
from myhost_draft import build_message


class DraftCopySyncTests(unittest.TestCase):
    def fixtures(self):
        original, source_rows, review_rows = [], [], []
        old_body = ("Goedendag,\n\nBestaande informatie over de zaak.\n\n"
                    "Een voorstel dat naar bestaand contact verwijst.\n\n"
                    "Zal ik iets voorstellen?\n\n" + target.OPT +
                    "\n\nGroet,\nAndrew")
        improved = ("Goedendag,\n\nEen relevante mobiele keuze voor bezoekers "
                    "kan naar de bestaande contactroute leiden.\n\n"
                    "Zal ik een voorbeeld van deze keuze laten zien?\n\n" +
                    target.OPT + "\n\nGroet,\nAndrew")
        for n in range(1, 451):
            key = "draft-" + format(n, "032x")
            company = "Fictief Bedrijf " + str(n)
            email = "info" + str(n) + "@example.invalid"
            original.append({"draft_id":key,"company":company,"email":email})
            src = [""] * 16
            src[0]=str(n); src[1]=key; src[2]=company; src[3]=email
            src[5]="Oude onderwerpsregel"; src[6]=old_body
            src[8]="https://example.invalid"
            src[13]=("BRONBLOKKADE_NIET_VERSTUREN" if n<=38
                     else "VOOR_MENSELIJKE_EINDCONTROLE")
            source_rows.append(src)
            rev = [""] * 17
            rev[0]=str(n); rev[1]=key; rev[2]=company
            rev[3]="Nieuw onderwerp"; rev[4]=src[8]
            rev[6]="Een relevante mobiele keuze voor bezoekers kan naar de bestaande contactroute leiden."
            rev[7]="" if n<=38 else improved
            rev[8]="NIET AANPASSEN" if n<=38 else "FASE1_OPENING_GECONTROLEERD"
            rev[10]="HOLD_BRONCHECK" if 39<=n<=46 else "MENSELIJKE_EINDCONTROLE"
            rev[12]="9.2";rev[14]="FASE 1 / 100"
            rev[15]="ALLEEN CONCEPT - MENSELIJKE REVIEW"
            review_rows.append(rev)
        return original, source_rows, review_rows

    def test_exact_populations_from_only_private_sources(self):
        original, current, reviewed = self.fixtures()
        def read(_, __, where):
            return current if where.startswith("QA450Actueel") else reviewed
        with patch.object(target.historical, "load_rows", return_value=original), \
             patch.object(target.historical, "read", side_effect=read):
            records=target.load_private_scope(object())
        self.assertEqual(len(records), 450)
        self.assertEqual(sum(x["eligible"] for x in records.values()), 404)
        self.assertEqual(sum(x["hold"] for x in records.values()), 8)

    def test_score_and_source_change_fail_closed(self):
        original, current, reviewed = self.fixtures()
        reviewed[99][12]="8.9"
        with patch.object(target.historical, "load_rows", return_value=original), \
             patch.object(target.historical, "read", side_effect=[current, reviewed]):
            with self.assertRaisesRegex(RuntimeError, "review_score_below_nine"):
                target.load_private_scope(object())
        original, current, reviewed = self.fixtures()
        reviewed[77][1]="draft-"+"f"*32
        with patch.object(target.historical, "load_rows", return_value=original), \
             patch.object(target.historical, "read", side_effect=[current, reviewed]):
            with self.assertRaisesRegex(RuntimeError, "identity_or_copy"):
                target.load_private_scope(object())

    def test_classification_preserves_holds_and_unrelated(self):
        key="draft-"+ "a"*32; second="draft-"+ "b"*32
        first={"draft_id":key,"company":"Example",
               "email":"info@example.invalid", "source_url":"https://example.invalid",
               "subject":"Old", "body":"Old body"}
        improved={**first,"subject":"New","body":"New body"}
        hold={**first,"draft_id":second,"subject":"Held"}
        expected={key:{"old":first,"new":improved,"eligible":True,"hold":False},
                  second:{"old":hold,"new":hold,"eligible":False,"hold":True}}
        def packet(row, uid):
            return {"uid":str(uid),"draft_id":row["draft_id"],"draft_flag":True,
                    "flags":{b"\\DRAFT"},"sha256":str(uid),"message":build_message(row)}
        source={"1":packet(first,1),"2":packet(improved,2),"3":packet(hold,3)}
        groups=target.classify(source,expected)
        target.verify_new_complete(groups,expected)
        self.assertEqual(groups[second]["old"], ["3"])
        with self.assertRaisesRegex(RuntimeError,"held_draft_changed_or_missing"):
            target.classify({"1":packet(first,1),"2":packet(improved,2)},expected)
        with self.assertRaisesRegex(RuntimeError,"unrecognized"):
            target.classify({"1":packet({**first,"subject":"Edited by human"},1),
                             "2":packet(improved,2),"3":packet(hold,3)},expected)
        with self.assertRaisesRegex(RuntimeError,"unrelated_drafts_present"):
            target.classify({**source,"4":packet({**first,"draft_id":"draft-"+"c"*32},4)},expected)

    def test_targeted_clear_never_sends_email(self):
        script=(Path(__file__).resolve().parents[1] / "scripts" /
                "sync_review_openings.py").read_text()
        self.assertIn('if item["eligible"] or item["hold"]\n                    for u in staged[key]["old"]',script)
        self.assertIn('if item["eligible"] or item["hold"]\n                for u in again[key]["old"]',script)
        self.assertIn('client.uid("EXPUNGE", uid_list)',script)
        self.assertNotIn("client.expunge(", script)
        self.assertNotIn("import smtplib",script)
        self.assertNotIn("sendmail(",script)
        self.assertIn("private_review_changed_before_remove",script)

    def test_workflow_is_owner_gated_and_not_scheduled(self):
        workflow=(Path(__file__).resolve().parents[1] / ".github" /
                  "workflows" / "sync-review-openings.yml").read_text()
        self.assertIn("github.actor == 'Yolol100'",workflow)
        self.assertIn("github.event.issue.number == 1659",workflow)
        self.assertIn("LEADS_VALUEFIRST_404_AUDIT_ONLY:",workflow)
        self.assertIn("LEADS_VALUEFIRST_404_CLEAR_ALL_412_ONLY:",workflow)
        self.assertNotIn("workflow_dispatch:",workflow)
        self.assertNotIn("  schedule:",workflow)

    def test_held_draft_purged_only_after_new_copy_staged(self):
        key = "draft-" + "a"*32
        old = {"draft_id": key, "company": "Example",
               "email": "info@example.invalid", "source_url": "https://example.invalid",
               "subject": "Held", "body": "Old copy"}
        expected = {key: {"old": old, "new": old, "eligible": False, "hold": True}}
        record = {"uid": "1", "draft_id": key, "draft_flag": True,
                  "flags": {b"\\DRAFT"}, "sha256": "abc",
                  "message": build_message(old)}
        before = target.classify({"1":record}, expected)
        target.verify_new_complete(before, expected)
        after = target.classify({}, expected, held_cleared=True)
        target.verify_new_complete(after, expected, held_cleared=True)
        with self.assertRaisesRegex(RuntimeError, "held_draft_changed_or_missing"):
            target.classify({"1":record}, expected, held_cleared=True)

    def test_authorization_required(self):
        with patch.dict("os.environ",{"MAILBOX_VALUEFIRST_TASK":"bad",
                                    "MAILBOX_VALUEFIRST_MODE":"sync"}):
            self.assertEqual(target.main(), 1)


if __name__ == "__main__":
    unittest.main()
