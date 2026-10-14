import unittest
from unittest.mock import Mock, patch

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
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
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


    def test_curly_placeholders_are_rejected_in_subject_and_body(self):
        for field in ("subject", "body"):
            for placeholder in ("{{bedrijfsnaam}}", "{{branche_meervoud}}", "{{voornaam}}", "{{"):
                with self.subTest(field=field, placeholder=placeholder):
                    row = dict(zip(q.HEADERS, self.row()[1]))
                    row[field] = placeholder + " voorbeeld"
                    with patch("draft_queue_readonly.is_public_http_url", return_value=True):
                        with self.assertRaisesRegex(RuntimeError, "draft_queue_unfilled_placeholder"):
                            q._validate_row(row)

    def test_body_limit_is_110_words_including_opt_out(self):
        row = dict(zip(q.HEADERS, self.row()[1]))
        row["body"] = "woord " * 110
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            self.assertEqual(len(q._validate_row(row)["body"].split()), 110)
        row["body"] += "extra"
        with patch("draft_queue_readonly.is_public_http_url", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "draft_queue_body_word_limit_exceeded"):
                q._validate_row(row)


if __name__ == "__main__":
    unittest.main()
