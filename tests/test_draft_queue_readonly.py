import unittest
from unittest.mock import Mock

import draft_queue_readonly as q


class DraftQueueTests(unittest.TestCase):
    def row(self):
        return [q.HEADERS, [
            "draft-0123456789abcdef0123456789abcdef",
            "2026-10-14T18:00:00+02:00",
            "Voorbeeld BV",
            "info@voorbeeld.nl",
            "https://voorbeeld.nl/contact",
            "Vraag voor Voorbeeld BV",
            "Goedendag,\n\nKorte testmail.\n",
        ]]

    def test_reads_exactly_one_private_row(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": self.row()}
        session.get.return_value = response
        row = q.load_draft("draft-0123456789abcdef0123456789abcdef", session)
        self.assertEqual(row["email"], "info@voorbeeld.nl")
        session.post.assert_not_called()
        session.delete.assert_not_called()

    def test_missing_duplicate_and_bad_ids_fail(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": [q.HEADERS]}
        session.get.return_value = response
        with self.assertRaises(RuntimeError):
            q.load_draft("draft-0123456789abcdef0123456789abcdef", session)
        with self.assertRaises(RuntimeError):
            q.load_draft("not-an-id", session)

    def test_header_drift_fails_closed(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": [["draft_id", "email"]]}
        session.get.return_value = response
        with self.assertRaises(RuntimeError):
            q.load_draft("draft-0123456789abcdef0123456789abcdef", session)

    def test_control_characters_in_subject_fail(self):
        values = self.row()
        values[1][5] = "Subject\nBcc: bad@example.org"
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": values}
        session.get.return_value = response
        with self.assertRaises(RuntimeError):
            q.load_draft("draft-0123456789abcdef0123456789abcdef", session)

    def test_nonpublic_source_url_fails(self):
        values = self.row()
        values[1][4] = "http://127.0.0.1/contact"
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": values}
        session.get.return_value = response
        with self.assertRaises(RuntimeError):
            q.load_draft("draft-0123456789abcdef0123456789abcdef", session)


if __name__ == "__main__":
    unittest.main()
