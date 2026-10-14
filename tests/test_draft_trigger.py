import unittest
from draft_trigger import resolve_request

ID = "draft-0123456789abcdef0123456789abcdef"


class TriggerTests(unittest.TestCase):
    def test_owner_issue_comment(self):
        event = {"issue": {"number": 1659}, "comment": {
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

    def test_dispatch_accepts_only_opaque_id(self):
        self.assertEqual(resolve_request("workflow_dispatch", {}, {"draft_id": ID}), ID)
        with self.assertRaises(ValueError):
            resolve_request("workflow_dispatch", {}, {"draft_id": "info@example.org"})


if __name__ == "__main__":
    unittest.main()
