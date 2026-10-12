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
import _once_historical_v2_migration as migration


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

    def test_key_creation_is_one_time_and_no_repeat_after_readback(self):
        state = [VAULT_HEADERS]
        calls = []
        def read(*_):
            return [list(r) for r in state]
        def append(_session, _spreadsheet_id, _tab, rows):
            calls.append(rows)
            state.extend(rows)
        with patch.object(migration, "read_live_values", side_effect=read), \
             patch.object(migration, "append_values", side_effect=append):
            first = migration.get_or_create_key(object())
            second = migration.get_or_create_key(object())
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(state), 2)
        self.assertNotIn("BEGIN PRIVATE KEY", str(state))

    def test_weak_email_domain_cannot_be_promoted(self):
        from _once_profile_historical_unverified_domains import candidate_domain
        for email in ("support@gmail.com", "foo@outlook.com", "contact@ziggo.nl",
                      "sales@myshopify.com", "a@mail.com", "info@wordpress.com"):
            self.assertEqual(candidate_domain(email), "")
        self.assertEqual(candidate_domain("team@smallbusiness.nl"), "smallbusiness.nl")


if __name__ == "__main__":
    unittest.main()
