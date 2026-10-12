"""Synthetic, privacy-safe regression tests for keyed history exclusions."""
import hashlib
import hmac
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from dedupe_preflight import candidate_identity, match_candidate
from historical_suppression import (
    HEADERS, SOURCE_TOTAL, VERSION, email_or_domain_is_suppressed, hmac_key,
    key_check, suppression_row, token, validate_rows,
)
import _once_import_historical_hmac as migrator


def creds(k="KEY-ONE"):
    return json.dumps({"private_key": "-----BEGIN PRIVATE KEY-----\n" + k})


class HmacTests(unittest.TestCase):
    def setUp(self):
        self.key = b"synthetic-key-unrelated-to-real-provider"
        self.marker = key_check(self.key)

    def row(self, i, domain="example.nl"):
        return [
            VERSION, self.marker,
            token(self.key, "source", "00000000-0000-0000-0000-" + f"{i:012d}"),
            token(self.key, "email", f"person{i}@{domain}"),
            token(self.key, "domain", domain) if domain else "",
        ]

    def test_opaque_sha256_matches_email_or_verified_domain_only(self):
        parsed = validate_rows([HEADERS, self.row(1)], self.key, complete=False)
        record = suppression_row(parsed, self.key)
        self.assertEqual(
            match_candidate({"email": "person1@example.nl"}, [record])["matched_by"],
            ["historical_email"],
        )
        self.assertEqual(
            match_candidate({"email": "other@somewhere.org", "official_domain": "example.nl"}, [record])["matched_by"],
            ["historical_domain"],
        )
        self.assertIsNone(match_candidate({"email": "other@somewhere.org"}, [record]))
        self.assertNotIn("@", repr(parsed))
        self.assertNotIn("example.nl", repr(parsed))

    def test_different_hmac_secrets_are_not_interchangeable(self):
        with patch.dict(os.environ, {"LEAD_REGISTRY_SERVICE_ACCOUNT_JSON": creds("SYNTH-A")},
                        clear=True):
            a = hmac_key()
        with patch.dict(os.environ, {"LEAD_REGISTRY_SERVICE_ACCOUNT_JSON": creds("SYNTH-B")},
                        clear=True):
            b = hmac_key()
        self.assertNotEqual(a, b)
        self.assertNotEqual(token(a, "email", "person@example.nl"),
                            token(b, "email", "person@example.nl"))
        rows = [HEADERS, [
            VERSION, key_check(a), token(a, "source", "test-id"),
            token(a, "email", "person@example.nl"), "",
        ]]
        with self.assertRaisesRegex(RuntimeError, "key_mismatch"):
            validate_rows(rows, b, complete=False)

    def test_tampered_duplicate_missing_and_plaintext_fail_closed(self):
        rows = [HEADERS, self.row(1)]
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            validate_rows(rows, self.key, complete=True)
        with self.assertRaisesRegex(RuntimeError, "duplicate_record"):
            validate_rows(rows + [self.row(1)], self.key, complete=False)
        altered = self.row(2)
        altered[3] = "someone@example.nl"
        with self.assertRaisesRegex(RuntimeError, "hash_or_key_mismatch"):
            validate_rows([HEADERS, altered], self.key, complete=False)
        with self.assertRaisesRegex(RuntimeError, "headers_changed"):
            validate_rows([["email"], self.row(1)], self.key, complete=False)

    def test_absent_secret_always_holds(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "service_account_missing"):
                hmac_key()

    def test_1128_exact_tokens_are_verified_in_batches_of_100(self):
        source = []
        for i in range(SOURCE_TOTAL):
            source.append({
                "id": "00000000-0000-0000-0000-" + f"{i:012d}",
                "email": f"person{i}@example.nl",
                "payload": {},
            })
        stored = []
        calls = []
        def read(*_args):
            return [HEADERS] + [list(row) for row in stored]
        def append(_session, _spreadsheet, _tab, rows):
            self.assertLessEqual(len(rows), 100)
            calls.append(len(rows))
            stored.extend([list(row) for row in rows])
        with patch.object(migrator, "_get_source", return_value=source), \
             patch.object(migrator, "hmac_key", return_value=self.key), \
             patch.object(migrator, "_authorized_session", return_value=(object(), "service")), \
             patch.object(migrator, "read_live_values", side_effect=read), \
             patch.object(migrator, "append_values", side_effect=append), \
             redirect_stdout(io.StringIO()):
            result = migrator.run()
            result_replay = migrator.run()
        self.assertEqual(result["opaque_suppression_count"], SOURCE_TOTAL)
        self.assertEqual(result["new"], SOURCE_TOTAL)
        self.assertEqual(result_replay["new"], 0)
        self.assertEqual(result_replay["already_exact"], SOURCE_TOTAL)
        self.assertEqual(len(stored), SOURCE_TOTAL)
        self.assertEqual(calls, [100] * 11 + [28])
        self.assertFalse(result["plaintext_contacts_written"])
        self.assertFalse(result["email_sent"])

    def test_partial_previous_append_reconciles_without_duplication(self):
        source = [{
            "id": "00000000-0000-0000-0000-" + f"{i:012d}",
            "email": f"person{i}@example.nl", "payload": {},
        } for i in range(SOURCE_TOTAL)]
        expected = migrator._expected_rows(source, self.key)
        stored = [list(row) for row in expected[:100]]
        appended = []
        def read(*_args):
            return [HEADERS] + [list(row) for row in stored]
        def append(*args):
            records = args[-1]
            appended.extend(records)
            stored.extend([list(row) for row in records])
        with patch.object(migrator, "_get_source", return_value=source), \
             patch.object(migrator, "hmac_key", return_value=self.key), \
             patch.object(migrator, "_authorized_session", return_value=(object(), "service")), \
             patch.object(migrator, "read_live_values", side_effect=read), \
             patch.object(migrator, "append_values", side_effect=append), \
             redirect_stdout(io.StringIO()):
            result = migrator.run()
        self.assertEqual(result["already_exact"], 100)
        self.assertEqual(result["new"], 1028)
        self.assertEqual(len(stored), SOURCE_TOTAL)
        self.assertEqual(len({row[2] for row in stored}), SOURCE_TOTAL)

    def test_conflicting_existing_hash_aborts_before_append(self):
        source = [{
            "id": "00000000-0000-0000-0000-" + f"{i:012d}",
            "email": f"person{i}@example.nl", "payload": {},
        } for i in range(SOURCE_TOTAL)]
        stored = [migrator._expected_rows(source, self.key)[0]]
        stored[0] = list(stored[0])
        stored[0][4] = token(self.key, "domain", "wrong.example")
        with patch.object(migrator, "_get_source", return_value=source), \
             patch.object(migrator, "hmac_key", return_value=self.key), \
             patch.object(migrator, "_authorized_session", return_value=(object(), "service")), \
             patch.object(migrator, "read_live_values", return_value=[HEADERS] + stored), \
             patch.object(migrator, "append_values") as writer:
            with self.assertRaisesRegex(RuntimeError, "conflicting_existing_row"):
                migrator.run()
        writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
