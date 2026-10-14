import unittest
from unittest.mock import patch
from email import policy
from email.parser import BytesParser

import myhost_draft as d

ROW = {
    "draft_id": "draft-0123456789abcdef0123456789abcdef",
    "company": "Voorbeeld BV",
    "email": "info@voorbeeld.nl",
    "source_url": "https://voorbeeld.nl/contact",
    "subject": "Vraag voor Voorbeeld BV",
    "body": "Goedendag,\n\nKorte testmail.",
}


class FakeIMAP:
    def __init__(self, existing=None):
        self.messages = list(existing or [])
        self.append_calls = 0
        self.selected = None
    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "Drafts"']
    def select(self, folder, readonly=True):
        self.selected = (folder, readonly)
        return "OK", [str(len(self.messages)).encode()]
    def search(self, charset, *criteria):
        ids=[]
        target=ROW["draft_id"]
        for i,(raw,flags) in enumerate(self.messages,1):
            msg=BytesParser(policy=policy.default).parsebytes(raw)
            if msg.get(d.DRAFT_HEADER)==target:
                ids.append(str(i).encode())
        return "OK", [b" ".join(ids)]
    def fetch(self, seq, query):
        raw,flags=self.messages[int(seq)-1]
        return "OK", [(b'1 (FLAGS ('+flags+b') RFC822 {123}', raw), b')']
    def append(self, folder, flags, date_time, raw):
        self.append_calls += 1
        self.messages.append((raw, b'\\Draft'))
        return "OK", [b"APPENDUID 1 1"]


class MyHostDraftTests(unittest.TestCase):
    def test_detects_drafts_folder(self):
        self.assertEqual(d.find_drafts_folder(FakeIMAP()), "Drafts")

    def test_list_accepts_unquoted_mailbox_atom_after_hierarchy_delimiter(self):
        class UnquotedIMAP(FakeIMAP):
            def list(self):
                return "OK", [rb'(\HasNoChildren \Drafts) "." INBOX.Drafts']
        self.assertEqual(d.find_drafts_folder(UnquotedIMAP()), "INBOX.Drafts")

    def test_list_accepts_quoted_mailbox_after_hierarchy_delimiter(self):
        class QuotedIMAP(FakeIMAP):
            def list(self):
                return "OK", [rb'(\HasNoChildren \Drafts) "." "INBOX.Drafts"']
        self.assertEqual(d.find_drafts_folder(QuotedIMAP()), "INBOX.Drafts")

    def test_list_rejects_ambiguous_special_use_drafts_folders(self):
        class AmbiguousIMAP(FakeIMAP):
            def list(self):
                return "OK", [
                    rb'(\HasNoChildren \Drafts) "." INBOX.Drafts',
                    rb'(\HasNoChildren \Drafts) "." Other.Drafts',
                ]
        with self.assertRaisesRegex(RuntimeError, "drafts_folder_missing_or_ambiguous"):
            d.find_drafts_folder(AmbiguousIMAP())

    def test_creates_and_reads_back_without_smtp(self):
        client=FakeIMAP()
        with patch("myhost_draft.time.sleep", return_value=None):
            result=d.save_draft(client,"Drafts",ROW)
        self.assertEqual(result,"created")
        self.assertEqual(client.append_calls,1)
        self.assertEqual(len(client.messages),1)

    def test_exact_existing_is_idempotent(self):
        msg=d.build_message(ROW)
        client=FakeIMAP([(msg.as_bytes(), b'\\Draft')])
        result=d.save_draft(client,"Drafts",ROW)
        self.assertEqual(result,"existing")
        self.assertEqual(client.append_calls,0)

    def test_changed_existing_fails_instead_of_overwriting(self):
        changed=dict(ROW); changed["subject"]="Andere titel"
        msg=d.build_message(changed)
        client=FakeIMAP([(msg.as_bytes(), b'\\Draft')])
        with self.assertRaises(RuntimeError):
            d.save_draft(client,"Drafts",ROW)
        self.assertEqual(client.append_calls,0)

    def test_no_draft_flag_fails(self):
        msg=d.build_message(ROW)
        client=FakeIMAP([(msg.as_bytes(), b'\\Seen')])
        with self.assertRaises(RuntimeError):
            d.save_draft(client,"Drafts",ROW)


if __name__ == "__main__":
    unittest.main()
