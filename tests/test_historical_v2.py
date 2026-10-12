"""Private-key-vault / business email domain fail-closed regression checks."""
from __future__ import annotations

import hashlib
import hmac
import unittest
from unittest.mock import patch

from historical_v2 import (
    HEADERS, VAULT_HEADERS, KEY_VERSION, VERSION, SOURCE_TOTAL,
    derive_key, key_from_vault, key_check, parse_rows, row_for_match, token,
)
from dedupe_preflight import match_candidate


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.secret = "1a" * 32
        self.key = derive_key(self.secret)

    def vault(self):
        return [VAULT_HEADERS, [KEY_VERSION, self.secret, "active"]]

    def row(self, index, official=False, corp=False):
        return [
            VERSION, key_check(self.key),
            token(self.key, "source", f"lead-{index:04d}"),
            token(self.key, "email", f"mail{index}@business.example"),
            token(self.key, "official", "business.example") if official else "",
            token(self.key, "corporate", "business.example") if corp else "",
        ]

    def test_key_is_independent_from_google_service_account_credentials(self):
        values = self.vault()
        with patch.dict("historical_v2.__dict__", {}, clear=False):
            first = key_from_vault(values)
        second = key_from_vault(values)
        self.assertEqual(first, second)
        self.assertNotEqual(first, bytes.fromhex(self.secret))

    def test_missing_or_multiple_vault_key_is_rejected(self):
        for rows in ([], [VAULT_HEADERS], self.vault() + [self.vault()[1]], [
            VAULT_HEADERS, [KEY_VERSION, self.secret, "retired"],
        ]):
            with self.assertRaises(RuntimeError):
                key_from_vault(rows)

    def test_corporate_fallback_does_not_block_gmail_or_other_domains(self):
        parsed = parse_rows([HEADERS, self.row(1, corp=True)], self.key, complete=False)
        guard = row_for_match(parsed, self.key)
        self.assertEqual(
            match_candidate({"official_domain": "business.example"}, [guard])["matched_by"],
            ["historical_v2_corporate_mail_domain"],
        )
        self.assertIsNone(match_candidate({"email": "other@gmail.com"}, [guard]))
        self.assertIsNone(match_candidate({"official_domain": "unrelated.example"}, [guard]))
        self.assertEqual(
            match_candidate({"email": "mail1@business.example"}, [guard])["matched_by"],
            ["historical_v2_email"],
        )

    def test_old_key_hash_cannot_be_used_with_new_vault(self):
        other = derive_key("2b" * 32)
        with self.assertRaisesRegex(RuntimeError, "bad_hash"):
            parse_rows([HEADERS, self.row(1, corp=True)], other, complete=False)

    def test_incomplete_key_mismatch_duplicate_or_leak_fail_closed(self):
        r = self.row(1, corp=True)
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            parse_rows([HEADERS, r], self.key, complete=True)
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            parse_rows([HEADERS, r, r], self.key, complete=False)
        malformed = list(r)
        malformed[5] = "rawdomain.example"
        with self.assertRaisesRegex(RuntimeError, "bad_hash"):
            parse_rows([HEADERS, malformed], self.key, complete=False)

    def test_final_1128_three_way_partition_and_batched_replay(self):
        rows = [HEADERS]
        rows += [self.row(i, official=i < 914, corp=914 <= i < 1060) for i in range(SOURCE_TOTAL)]
        parsed = parse_rows(rows, self.key, complete=True)
        self.assertEqual(parsed["count"], 1128)
        self.assertEqual(parsed["official_count"], 914)
        self.assertEqual(parsed["corporate_count"], 146)
        self.assertEqual(
            sum(not r[4] and not r[5] for r in rows[1:]), 68,
        )

    def test_production_read_requires_key_vault_and_complete_hashes(self):
        from historical_v2 import read_production_state, VAULT_SHEET_ID, VAULT_TAB, TAB_NAME
        rows = [HEADERS] + [
            self.row(i, official=i < 914, corp=914 <= i < 1060)
            for i in range(SOURCE_TOTAL)
        ]
        calls = []
        def read(_session, spreadsheet_id, tab):
            calls.append((spreadsheet_id, tab))
            return self.vault() if tab == VAULT_TAB else rows
        result = read_production_state(object(), read, "original-public-sheet")
        self.assertEqual(result["status"], "historical_v2_suppression")
        self.assertEqual(calls, [
            (VAULT_SHEET_ID, VAULT_TAB),
            ("original-public-sheet", TAB_NAME),
        ])



if __name__ == "__main__":
    unittest.main()
