"""In-memory protocol tests for bounded bulk reads; no real mailbox access."""
import re
import unittest
from unittest.mock import Mock, patch

import replace450 as core
import replace450_fast as fast
from test_replace450 import MemoryMailbox, make_rows, plan_for


class BatchMailbox(MemoryMailbox):
    def __init__(self,count=3):
        super().__init__(count)
        self.fetch_calls=[]
        self.omit_metadata=False
        self.omit_body=False
        self.oversize=False
        self.change_flags=False

    def uid(self,command,*args):
        if command.upper()!="FETCH":
            return super().uid(command,*args)
        uids=str(args[0]).split(",")
        self.fetch_calls.append((tuple(uids),str(args[1])))
        result=[]
        for uid in reversed(uids):
            status,values=super().uid(command,uid,*args[1:])
            self.assert_status=status
            result.extend(values)
        if "BODY.PEEK" not in str(args[1]):
            if self.omit_metadata:
                result=result[:-1]
            if self.oversize and result:
                result[0]=re.sub(rb"RFC822.SIZE [0-9]+",b"RFC822.SIZE 9000000",result[0])
        else:
            if self.omit_body:
                result=result[2:]
            if self.change_flags and result and isinstance(result[0],tuple):
                head,raw=result[0]
                result[0]=(head.replace(b"\\DRAFT",b"\\SEEN"),raw)
        return "OK",result


class FastReadTests(unittest.TestCase):
    def test_batch_hashes_and_content_match_individual_readback(self):
        m=BatchMailbox(12)
        old=core.scan(m)
        m.fetch_calls=[]
        new=fast.scan(m)
        self.assertEqual(set(old),set(new))
        for uid in old:
            self.assertEqual(old[uid]["sha256"],new[uid]["sha256"])
            self.assertEqual(old[uid]["draft_id"],new[uid]["draft_id"])
            self.assertEqual(old[uid]["flags"],new[uid]["flags"])
        self.assertEqual(len(m.fetch_calls),2)
        self.assertEqual(len(m.fetch_calls[0][0]),12)

    def test_hundred_message_read_chunks(self):
        m=BatchMailbox(205)
        result=fast.scan(m)
        self.assertEqual(len(result),205)
        self.assertEqual(len(m.fetch_calls),6)
        self.assertTrue(all(len(uids)<=100 for uids,_ in m.fetch_calls))

    def test_missing_metadata_or_oversize_prevents_body_fetch(self):
        for problem in ("omit_metadata","oversize"):
            with self.subTest(problem=problem):
                m=BatchMailbox(3)
                setattr(m,problem,True)
                with self.assertRaises(RuntimeError):
                    fast.scan(m)
                self.assertEqual(len(m.fetch_calls),1)
                self.assertNotIn("BODY.PEEK",m.fetch_calls[0][1])

    def test_missing_message_or_changed_draft_flag_blocks_readback(self):
        for problem in ("omit_body","change_flags"):
            with self.subTest(problem=problem):
                m=BatchMailbox(3)
                setattr(m,problem,True)
                with self.assertRaises(RuntimeError):
                    fast.scan(m)

    def test_existing_replacement_contract_with_fast_reads(self):
        m=BatchMailbox(3)
        plan=plan_for(m)
        rows=make_rows()
        with patch.object(core,"scan",side_effect=fast.scan),patch("myhost_draft.save_draft",side_effect=m.save):
            result=core.replace(m,"Drafts","7",plan,rows,recheck=Mock(),progress=Mock())
        self.assertEqual(result,{"stored":450,"deleted":3,"sent":0})
        self.assertEqual(len(m.messages),450)
        self.assertEqual([c[1] for c in m.calls if c[0]=="UID EXPUNGE"],["1,2,3"])

    def test_phase_wrapper_restores_original_functions(self):
        scan=core.scan
        verify=core.verify_new
        with patch.object(core,"inspect_mailbox",return_value={"old_drafts":0}) as inspection:
            self.assertEqual(fast.run_phase("inspect"),{"old_drafts":0})
        inspection.assert_called_once()
        self.assertIs(core.scan,scan)
        self.assertIs(core.verify_new,verify)


if __name__=="__main__":
    unittest.main()
