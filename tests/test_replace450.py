"""Only synthetic in-memory mailboxes. No external mail, credentials or HTTP."""
import copy
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock, patch

import review450 as b
import replace450 as r
from myhost_draft import build_message


def make_rows(n=450):
    out=[]
    for i in range(n):
        site="https://fictief-{}.example.net/".format(i)
        item={"company":"Fictief Schildersbedrijf {}".format(i),"website":site,
              "email":"info@fictief-{}.example.net".format(i),"source_url":site,
              "cluster":1,"branche_meervoud":"schilders","greeting":"Goedendag,",
              "status":"verified_website_and_email"}
        out.append(b.make_copy(item,[(site,"Fictief schilderwerk houtrotherstel")],"test"))
    return out


class MemoryMailbox:
    def __init__(self,count=3):
        self.messages={}
        self.calls=[]
        self.validity="7"
        self.supported=True
        self.saves=0
        self.fail_at=None
        self.id_index={}
        for i in range(count):
            draft_id="draft-"+format(i+1000,"032x")
            msg=build_message({"draft_id":draft_id,
                 "email":"info@old-{}.example.org".format(i),"subject":"Old fictional review",
                 "body":"Goedendag,\n\nFictieve oorspronkelijke inhoud.\n\nGroet,\nAndrew"})
            uid=str(i+1)
            self.messages[uid]=(msg.as_bytes(),{b"\\DRAFT"})
            self.id_index[draft_id]=uid
        self.next_uid=100

    def capability(self):
        return "OK",[b"IMAP4rev1 UIDPLUS" if self.supported else b"IMAP4rev1"]

    def select(self,folder,readonly=True):
        self.calls.append(("SELECT",folder,readonly))
        return "OK",[str(len(self.messages)).encode()]

    def response(self,kind):
        return kind,[self.validity.encode()]

    def uid(self,command,*args):
        command=command.upper()
        if command=="SEARCH":
            return "OK",[" ".join(sorted(self.messages,key=int)).encode()]
        if command=="FETCH":
            uid=str(args[0]);raw,flags=self.messages[uid]
            meta=("1 (UID "+uid+" FLAGS (").encode()+b" ".join(flags)+(") RFC822.SIZE "+str(len(raw))+ ")").encode()
            if "BODY.PEEK" in str(args[1]):
                return "OK",[(meta,raw),b")"]
            return "OK",[meta]
        if command=="STORE":
            self.calls.append(("STORE",str(args[0])))
            for uid in str(args[0]).split(","):
                raw,flags=self.messages[uid]
                self.messages[uid]=(raw,flags|{b"\\DELETED"})
            return "OK",[]
        if command=="EXPUNGE":
            self.calls.append(("UID EXPUNGE",str(args[0])))
            for uid in str(args[0]).split(","):
                if uid in self.messages and b"\\DELETED" in self.messages[uid][1]:
                    del self.messages[uid]
            return "OK",[]
        raise AssertionError("Unsupported test command")

    def save(self,_client,_folder,row,**_kwargs):
        self.saves+=1
        if self.fail_at==self.saves:
            raise RuntimeError("imap_append_failed")
        # Only the synthetic server's ID lookup is indexed. Production content
        # verification below still parses every message and checks all fields.
        uid=self.id_index.get(row["draft_id"])
        if uid in self.messages:
            return "existing"
        self.next_uid+=1
        uid=str(self.next_uid)
        self.messages[uid]=(build_message(row).as_bytes(),{b"\\DRAFT"})
        self.id_index[row["draft_id"]]=uid
        return "created"


def plan_for(mailbox):
    return {uid:{"sha256":rec["sha256"],"draft_id":rec["draft_id"],"draft_flag":rec["draft_flag"]}
            for uid,rec in r.scan(mailbox).items()}


class ReplacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=make_rows()

    def test_449_never_stores_or_deletes(self):
        m=MemoryMailbox();plan=plan_for(m)
        with patch("myhost_draft.save_draft",side_effect=m.save):
            with self.assertRaisesRegex(RuntimeError,"precondition"):
                r.replace(m,"Drafts","7",plan,self.rows[:-1],recheck=Mock(),progress=Mock())
        self.assertEqual(m.saves,0)
        self.assertFalse(any(c[0]=="STORE" for c in m.calls))

    def test_no_uidplus_never_stores_or_deletes(self):
        m=MemoryMailbox();plan=plan_for(m);m.supported=False
        with patch("myhost_draft.save_draft",side_effect=m.save):
            with self.assertRaisesRegex(RuntimeError,"uid_expunge"):
                r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=Mock())
        self.assertEqual(m.saves,0)
        self.assertFalse(any(c[0]=="STORE" for c in m.calls))

    def test_complete_450_exact_readback_then_only_old_uids_deleted(self):
        m=MemoryMailbox();plan=plan_for(m);progress=Mock()
        with patch("myhost_draft.save_draft",side_effect=m.save):
            result=r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=progress)
        self.assertEqual(result,{"stored":450,"deleted":3,"sent":0})
        self.assertEqual(len(m.messages),450)
        deleted=[c[1] for c in m.calls if c[0]=="UID EXPUNGE"]
        self.assertEqual(deleted,["1,2,3"])
        self.assertTrue(all(u not in m.messages for u in plan))
        self.assertEqual(len(r.verify_new(r.scan(m),self.rows)),450)
        self.assertEqual(progress.call_args.args,("completed",450,3))
        with patch("myhost_draft.save_draft",side_effect=m.save):
            result2=r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=Mock())
        self.assertEqual(result2["stored"],450)
        self.assertEqual(len(m.messages),450)
        self.assertEqual(len([c for c in m.calls if c[0]=="UID EXPUNGE"]),1)

    def test_save_failure_keeps_every_original_message(self):
        m=MemoryMailbox();plan=plan_for(m);m.fail_at=7
        with patch("myhost_draft.save_draft",side_effect=m.save):
            with self.assertRaisesRegex(RuntimeError,"append_failed"):
                r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=Mock())
        self.assertTrue(set(plan)<=set(m.messages))
        self.assertFalse(any(c[0]=="STORE" for c in m.calls))

    def test_edited_old_draft_is_never_overwritten_or_deleted(self):
        m=MemoryMailbox();plan=plan_for(m)
        raw,flags=m.messages["1"];m.messages["1"]=(raw+b"changed",flags)
        with patch("myhost_draft.save_draft",side_effect=m.save):
            with self.assertRaisesRegex(RuntimeError,"old_draft_changed"):
                r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=Mock())
        self.assertEqual(m.saves,0)
        self.assertFalse(any(c[0]=="STORE" for c in m.calls))

    def test_nondraft_or_changed_uidvalidity_blocks_replacement(self):
        for scenario in ("nondraft","validity"):
            with self.subTest(scenario=scenario):
                m=MemoryMailbox();plan=plan_for(m)
                if scenario=="nondraft":
                    plan["1"]["draft_flag"]=False
                else:
                    m.validity="8"
                with self.assertRaises(RuntimeError):
                    r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=Mock())
                self.assertEqual(m.saves,0)
                self.assertFalse(any(c[0]=="STORE" for c in m.calls))

    def test_new_unrelated_message_after_inventory_blocks(self):
        m=MemoryMailbox();plan=plan_for(m)
        m.messages["99"]=m.messages["1"]
        with self.assertRaisesRegex(RuntimeError,"unrelated"):
            r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=Mock())
        self.assertFalse(any(c[0]=="STORE" for c in m.calls))

    def test_private_hash_must_be_reviewed_before_mailbox_access(self):
        values=[b.COLS]+[[row[k] for k in b.COLS] for row in self.rows]
        checksum=b.digest(values)
        control={"approved_content_sha256":checksum,"review_status":"source_and_copy_reviewed"}
        state={"status":"ready_for_review","content_sha256":checksum}
        self.assertEqual(r.validate_batch(self.rows,control,state),checksum)
        control["approved_content_sha256"]="wrong"
        with self.assertRaisesRegex(RuntimeError,"not_reviewed"):
            r.validate_batch(self.rows,control,state)

    def test_bad_replacement_readback_keeps_old_drafts(self):
        m=MemoryMailbox();plan=plan_for(m)
        def save(client,folder,row,**kw):
            result=m.save(client,folder,row,**kw)
            if m.saves==450:
                raw,flags=m.messages[str(m.next_uid)]
                m.messages[str(m.next_uid)]=(raw+b"mismatch",flags)
            return result
        with patch("myhost_draft.save_draft",side_effect=save):
            with self.assertRaisesRegex(RuntimeError,"readback_mismatch"):
                r.replace(m,"Drafts","7",plan,self.rows,recheck=Mock(),progress=Mock())
        self.assertTrue(set(plan)<=set(m.messages))
        self.assertFalse(any(c[0]=="STORE" for c in m.calls))

    def test_inventory_stores_no_old_message_content(self):
        vals=r.plan_values(r.scan(MemoryMailbox()))
        self.assertEqual(vals[0],r.PLAN_COLS)
        self.assertTrue(all(len(row)==4 for row in vals))
        self.assertNotIn("Fictieve oorspronkelijke inhoud",str(vals))
        self.assertNotIn("info@old-",str(vals))


if __name__=="__main__":
    unittest.main()
