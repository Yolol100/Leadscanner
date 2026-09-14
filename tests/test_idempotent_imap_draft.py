import unittest
from types import SimpleNamespace

from outreach_idempotent_imap_draft import ensure_verified_draft


class FakeImap:
    def __init__(self, *args, existing=(), **kwargs):
        self.ids=list(existing)
        self.append_calls=0
    def login(self,*a): return ("OK", [])
    def list(self): return ("OK", [b'(\\Drafts) "/" "Drafts"'])
    def select(self,*a,**k): return ("OK", [])
    def search(self,*a): return ("OK", [b" ".join(i.encode() for i in self.ids)])
    def append(self,*a):
        self.append_calls += 1
        self.ids.append("77")
        return ("OK", [])
    def logout(self): return ("BYE", [])


def mailbox():
    return SimpleNamespace(mailbox_id="primary", sender_name="Andrew", sender_email="me@example.test", mail_user="me@example.test", mail_password="secret", imap_host="imap.example.test", imap_port=993)


class IdempotentDraftTests(unittest.TestCase):
    def test_existing_single_draft_is_reused_without_append(self):
        fake=FakeImap(existing=("42",))
        receipt=ensure_verified_draft(mailbox(),recipient="lead@example.test",subject="Re: hi",body="Thanks",test_id="positive-reply-"+"a"*32,imap_factory=lambda *a,**k: fake)
        self.assertEqual(receipt.message_ids,("42",))
        self.assertEqual(fake.append_calls,0)

    def test_missing_draft_is_appended_once_and_read_back_exactly(self):
        fake=FakeImap()
        receipt=ensure_verified_draft(mailbox(),recipient="lead@example.test",subject="Re: hi",body="Thanks",test_id="positive-reply-"+"b"*32,imap_factory=lambda *a,**k: fake,delay_seconds=0)
        self.assertEqual(receipt.message_ids,("77",))
        self.assertEqual(fake.append_calls,1)

    def test_duplicate_existing_drafts_fail_closed(self):
        fake=FakeImap(existing=("1","2"))
        with self.assertRaisesRegex(RuntimeError,"multiple drafts"):
            ensure_verified_draft(mailbox(),recipient="lead@example.test",subject="Re: hi",body="Thanks",test_id="positive-reply-"+"c"*32,imap_factory=lambda *a,**k: fake)
        self.assertEqual(fake.append_calls,0)


if __name__ == "__main__":
    unittest.main()
