"""Synthetic-only tests for private, read-only historical IMAP verification."""
from datetime import datetime, timezone
from email.message import EmailMessage
from unittest.mock import patch
import contextlib
from io import StringIO
import os
import unittest

from historical_v2 import token
import _once_historical_myhost_audit as audit


class FakeIMAP:
    def __init__(self, message):
        self.message = message
        self.writes = []
        self.readonly = []
    def select(self, folder, readonly=True):
        self.readonly.append(readonly)
        return "OK", [b"1"]
    def search(self, charset, *terms):
        if terms and terms[0] == "ALL":
            return "OK", [b"1"]
        if terms and terms[0] == "HEADER":
            return "OK", [b"1"]
        if terms and terms[0] == "TO":
            return "OK", [b""]
        return "NO", []
    def fetch(self, mid, query):
        if query == "(UID)":
            return "OK", [b"1 (UID 12)"]
        return "OK", [(b"1 (RFC822)", self.message.as_bytes())]
    def uid(self, command, *args):
        if command.lower() != "fetch":
            self.writes.append(command)
            raise AssertionError("No write allowed")
        return "OK", [b"1 (UID 12 FLAGS (\\Draft))"]
    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "Drafts"',
                      b'(\\HasNoChildren) "/" "Sent"']
    def getquotaroot(self, folder):
        return "OK", [b'Drafts (STORAGE 40 1000)']


class AuditTests(unittest.TestCase):
    def _msg(self, key):
        recipient = "info@sample.nl"
        mail = EmailMessage()
        mail["From"] = "Andrew Baeten <info@andrewbaeten.nl>"
        mail["To"] = recipient
        mail["Subject"] = "een voorstel voor sample"
        mail["Date"] = "Tue, 13 Oct 2026 02:10:00 +0200"
        mail["Message-ID"] = "<synthetic@example.invalid>"
        mail["X-Leadscanner-Lead-ID"] = (
            "growth-" + token(key, "email", recipient)[:20])
        mail["X-Leadscanner-Review-Required"] = "contact-basis"
        mail.set_content(
            "Hoi,\n\nOp jullie website vielen me deze concrete punten op:\n"
            "- punt een\n- punt twee\n- punt drie\n- punt vier\n\n"
            "Ik kan een kort voorbeeld uitwerken. Zal ik dat opsturen?\n\n"
            "Geen interesse: dan stop ik.\n\nGroet,\nAndrew Baeten\n"
        )
        return mail

    def test_exact_live_private_inventory_never_mutates_imap(self):
        key = b"synthetic-secret-key-012345678901"
        fake = FakeIMAP(self._msg(key))
        with patch.dict(os.environ, {"OUTREACH_SENDER_EMAIL": "info@andrewbaeten.nl"}):
            records, report = audit.inventory(
                fake, "Drafts",
                {"v2_key": key}, {"sample.nl"},
            )
        self.assertEqual(report["run_drafts"], 1)
        self.assertEqual(report["copy_template_pass"], 1)
        self.assertEqual(report.get("identity_failure", 0), 0)
        self.assertEqual(report.get("review_flag_failure", 0), 0)
        self.assertEqual(report.get("draft_flag_failure", 0), 0)
        self.assertEqual(report.get("duplicate_identity", 0), 0)
        self.assertEqual(report.get("recipients_with_sent_mail", 0), 0)
        self.assertEqual(report["quota_available"], 1)
        self.assertEqual(len(records), 1)
        self.assertTrue(fake.readonly)
        self.assertTrue(all(fake.readonly))
        self.assertEqual(fake.writes, [])

    def test_no_identifiers_or_message_text_in_summary(self):
        source = {"source_checked": 1128, "source_hmac_suppressed": 1128}
        box = {"historic_drafts": 43, "run_drafts": 43,
               "copy_template_pass": 43}
        with patch.object(audit, "source_and_mailbox_snapshot",
                          return_value=(None,None,None,source,[],box)):
            result = audit.inventory_report()
        self.assertEqual(result["status"], "green")
        self.assertNotIn("@", str(result))
        self.assertNotIn("sample.nl", str(result))

    def test_any_bad_draft_blocks_mailbox_acceptance(self):
        source = {"source_checked": 1128, "source_hmac_suppressed": 1128}
        box = {"historic_drafts": 43, "run_drafts": 43,
               "identity_failure": 1, "copy_template_pass": 42}
        with patch.object(audit, "source_and_mailbox_snapshot",
                          return_value=(None,None,None,source,[],box)):
            self.assertEqual(audit.inventory_report()["status"], "hold")

    def test_private_exception_message_is_suppressed(self):
        sensitive = "private lead contact@sample.nl secret"
        out = StringIO()
        with patch("sys.argv", ["audit", "--mode", "inventory"]), \
             patch.object(audit, "inventory_report",
                          side_effect=RuntimeError(sensitive)), \
             contextlib.redirect_stdout(out):
            code = audit.main()
        self.assertEqual(code, 1)
        self.assertIn("HISTORICAL_INDEPENDENT_AUDIT=red", out.getvalue())
        self.assertNotIn("sample.nl", out.getvalue())
        self.assertNotIn("secret", out.getvalue())
        self.assertNotIn("@", out.getvalue())


if __name__ == "__main__":
    unittest.main()
