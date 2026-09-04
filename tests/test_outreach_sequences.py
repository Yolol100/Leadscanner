import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_sequences as s
from outreach_mailboxes import MailboxConfig


def mailbox():
    return MailboxConfig(mailbox_id="m1",enabled=True,smtp_host="mail.example.com",smtp_port=587,imap_host="mail.example.com",imap_port=993,mail_user="andrew@example.com",mail_password="secret",sender_name="Andrew",sender_email="andrew@example.com",daily_limit=20,min_wait_minutes=1,dkim_selector="x",required_spf_token="include:spf.example.com")


def row(step, variant="A", **extra):
    value={"lead_id":"lead-1","sequence_id":"seq-1","sequence_version":"1","step_number":str(step),"variant_id":variant,"enabled":"true","subject":"Subject" if step==1 else "","body":f"Body {step}{variant}","wait_minutes":"0" if step==1 else "60","status":"approved","selected":"","scheduled_at":"","sent_at":"","message_id":"","sender_mailbox_id":"","sender_email":"","last_error":"","source":"test"}
    value.update(extra); return value


class OutreachSequenceTests(unittest.TestCase):
    def test_contract_accepts_multi_step_variants(self):
        self.assertEqual(s.validate_sequence_rows([row(1,"A"),row(1,"B"),row(2,"A"),row(2,"B"),row(3,"A")]), [])

    def test_contract_rejects_more_than_26_variants(self):
        rows=[row(1,chr(ord("A")+(i%26)),source=str(i)) for i in range(27)]
        self.assertTrue(any("duplicate sequence step/variant" in item for item in s.validate_sequence_rows(rows)))

    def test_contract_rejects_wait_mismatch_between_variants(self):
        errors=s.validate_sequence_rows([row(1,"A"),row(2,"A",wait_minutes="60"),row(2,"B",wait_minutes="120")])
        self.assertTrue(any("same wait_minutes" in item for item in errors))

    def test_variant_selection_is_stable(self):
        now=datetime(2026,9,4,10,0,tzinfo=timezone.utc); lead_rows=[(2,row(1,"A")),(3,row(1,"B")),(4,row(1,"C"))]
        first=s.next_sequence_action(lead_rows,now=now); second=s.next_sequence_action(lead_rows,now=now)
        self.assertEqual(first.variant_id, second.variant_id); self.assertIn(first.variant_id,{"A","B","C"})

    def test_step_two_waits_for_previous_send(self):
        now=datetime(2026,9,4,10,0,tzinfo=timezone.utc)
        step1=row(1,status="sent",selected="true",sent_at="2026-09-04T09:30:00Z",message_id="<first@example.com>")
        lead_rows=[(2,step1),(3,row(2,wait_minutes="60"))]
        self.assertIsNone(s.next_sequence_action(lead_rows,now=now))
        due=s.next_sequence_action(lead_rows,now=now+timedelta(minutes=31)); self.assertEqual(due.step_number,2); self.assertEqual(due.previous_message_id,"<first@example.com>"); self.assertEqual(due.effective_subject,"Subject")

    def test_followup_message_threads_to_previous_message(self):
        now=datetime(2026,9,4,11,0,tzinfo=timezone.utc)
        step1=row(1,status="sent",selected="true",sent_at="2026-09-04T09:00:00Z",message_id="<first@example.com>")
        action=s.next_sequence_action([(2,step1),(3,row(2,wait_minutes="60"))],now=now)
        msg=s.build_sequence_message({"lead_id":"lead-1","email":"lead@example.net"},action,mailbox())
        self.assertEqual(msg["In-Reply-To"],"<first@example.com>"); self.assertIn("<first@example.com>",msg["References"]); self.assertEqual(msg["Subject"],"Subject")

    def test_final_step_is_reported(self):
        now=datetime(2026,9,4,11,0,tzinfo=timezone.utc)
        step1=row(1,status="sent",selected="true",sent_at="2026-09-04T09:00:00Z",message_id="<first@example.com>")
        self.assertTrue(s.next_sequence_action([(2,step1),(3,row(2))],now=now).is_final_step)


if __name__ == "__main__": unittest.main()
