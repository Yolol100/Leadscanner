import os
import unittest
from unittest.mock import patch
from draft_trigger import resolve_request, resolve_batch_request

ID = "draft-0123456789abcdef0123456789abcdef"


class TriggerTests(unittest.TestCase):
    def test_owner_issue_comment(self):
        event = {"repository": {"full_name": "Yolol100/Leadscanner"},
                 "issue": {"number": 1659}, "comment": {
            "user": {"login": "Yolol100"},
            "author_association": "OWNER", "body": "LEADS_DRAFT_ONLY: " + ID}}
        self.assertEqual(resolve_request("issue_comment", event, {}), ID)

    def test_rejects_wrong_issue_or_user_or_extra_data(self):
        cases = [
            {"issue": {"number": 1660}, "comment": {"author_association": "OWNER", "body": "LEADS_DRAFT_ONLY: " + ID}},
            {"issue": {"number": 1659}, "comment": {"author_association": "NONE", "body": "LEADS_DRAFT_ONLY: " + ID}},
            {"issue": {"number": 1659}, "comment": {"author_association": "OWNER", "body": "LEADS_DRAFT_ONLY: " + ID + " email@example.org"}},
        ]
        for event in cases:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    resolve_request("issue_comment", event, {})

    def test_reject_nonowner_comment_even_with_collaborator_access(self):
        for login, association in (("OtherUser", "COLLABORATOR"), ("OtherUser", "MEMBER"),
                                   ("OtherUser", "OWNER"), ("Yolol100", "MEMBER")):
            event = {"repository": {"full_name": "Yolol100/Leadscanner"},
                     "issue": {"number": 1659},
                     "comment": {"user": {"login": login}, "author_association": association,
                                 "body": "LEADS_DRAFT_ONLY: " + ID}}
            with self.subTest(login=login, association=association):
                with self.assertRaises(ValueError):
                    resolve_request("issue_comment", event, {})

    def test_reject_cross_repo_and_pull_request_comment(self):
        for wrong in ({"repository": {"full_name": "Elsewhere/Leadscanner"},
                       "issue": {"number": 1659}},
                      {"repository": {"full_name": "Yolol100/Leadscanner"},
                       "issue": {"number": 1659, "pull_request": {"url": "fake"}}}):
            event = {**wrong, "comment": {"user": {"login": "Yolol100"},
                                        "author_association": "OWNER",
                                        "body": "LEADS_DRAFT_ONLY: " + ID}}
            with self.assertRaises(ValueError):
                resolve_request("issue_comment", event, {})

    def test_batch_owner_only(self):
        ids = "draft-" + "1" * 32 + ",draft-" + "2" * 32
        event = {"repository": {"full_name": "Yolol100/Leadscanner"},
                 "issue": {"number": 1659},
                 "comment": {"user": {"login": "Yolol100"}, "author_association": "OWNER",
                             "body": "LEADS_DRAFT_BATCH_ONLY: " + ids}}
        self.assertEqual(len(resolve_batch_request("issue_comment", event, {})), 2)
        event["comment"]["user"]["login"] = "OtherUser"
        with self.assertRaises(ValueError):
            resolve_batch_request("issue_comment", event, {})

    def test_dispatch_requires_exact_owner_and_main(self):
        for actor, ref in (("OtherUser", "refs/heads/main"),
                           ("Yolol100", "refs/heads/feature"),
                           ("", "refs/heads/main")):
            with self.subTest(actor=actor, ref=ref):
                with patch.dict(os.environ, {"GITHUB_ACTOR": actor, "GITHUB_REF": ref}):
                    with self.assertRaises(ValueError):
                        resolve_request("workflow_dispatch", {}, {"draft_id": ID})
                    with self.assertRaises(ValueError):
                        resolve_batch_request("workflow_dispatch", {},
                                              {"draft_ids": ID + "," + "draft-" + "2" * 32})

    def test_dispatch_accepts_only_opaque_id(self):
        with patch.dict(os.environ, {"GITHUB_ACTOR": "Yolol100", "GITHUB_REF": "refs/heads/main"}):
            self.assertEqual(resolve_request("workflow_dispatch", {}, {"draft_id": ID}), ID)
            with self.assertRaises(ValueError):
                resolve_request("workflow_dispatch", {}, {"draft_id": "info@example.org"})


if __name__ == "__main__":
    unittest.main()
