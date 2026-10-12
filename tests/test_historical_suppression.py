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



if __name__ == "__main__":
    unittest.main()
