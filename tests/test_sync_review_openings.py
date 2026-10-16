"""Synthetic privacy-safe staging recovery checks."""
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import sync_review_openings as s
from myhost_draft import build_message

class RecoverySafety(unittest.TestCase):
    def test_all_three_versions_and_held_purge(self):
        key="draft-"+"a"*32
        old={"draft_id":key,"company":"Example","email":"info@example.invalid",
             "source_url":"https://example.invalid","subject":"Original","body":"Original"}
        stale={**old,"subject":"Older reviewed","body":"Prior"}
        new={**old,"subject":"Latest reviewed","body":"Latest"}
        data={key:{"old":old,"new":new,"prior":stale,"eligible":True,"hold":False}}
        def record(row,uid):
            return {"uid":str(uid),"draft_id":key,"draft_flag":True,
                    "flags":{b"\\DRAFT"},"message":build_message(row),"sha256":str(uid)}
        staged=s.classify({"1":record(old,1),"2":record(stale,2),"3":record(new,3)},data)
        self.assertEqual(len(staged[key]["prior"]),1)
        s.verify_new_complete(staged,data)
        clean=s.classify({"3":record(new,3)},data,post=True)
        s.verify_new_complete(clean,data,post=True)
        with self.assertRaisesRegex(RuntimeError,"stale_drafts_remain"):
            s.classify({"2":record(stale,2),"3":record(new,3)},data,post=True)

    def test_no_smtp_or_global_expunge(self):
        script=(Path(__file__).resolve().parents[1]/"scripts"/"sync_review_openings.py").read_text()
        self.assertNotIn("import smtplib",script)
        self.assertNotIn("client.expunge(",script)
        self.assertNotIn("sendmail(",script)
        self.assertIn('client.uid("EXPUNGE", uid_list)',script)
        self.assertIn("private_review_changed_before_remove",script)
        self.assertIn("old_scope_not_exact_413",script)

    def test_owner_only_triggers(self):
        flow=(Path(__file__).resolve().parents[1]/".github"/"workflows"/"sync-review-openings.yml").read_text()
        self.assertIn("github.actor == 'Yolol100'",flow)
        self.assertIn("LEADS_VALUEFIRST_407_CLEAR_ALL_412_ONLY:",flow)
        self.assertNotIn("workflow_dispatch:",flow)

    def test_unauthorized_mode_fails(self):
        with patch.dict("os.environ",{"MAILBOX_VALUEFIRST_TASK":"wrong","MAILBOX_VALUEFIRST_MODE":"sync"}):
            self.assertEqual(s.main(),1)

if __name__=="__main__":
    unittest.main()
