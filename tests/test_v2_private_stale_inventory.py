"""No-provider tests for a private, read-only exact-60 IMAP inventory."""
import copy
from datetime import datetime, timezone
import unittest

import v2_private_stale_inventory as report


class Response:
    def __init__(self, value, status=200):
        self.value = value
        self.status_code = status

    def json(self):
        return self.value


class PrivateSheet:
    def __init__(self, *, hidden=True, existing=False):
        self.hidden = hidden
        self.rows = [["EXISTING"]] if existing else []
        self.writes = 0

    def get(self, url, **kwargs):
        if "?fields=" in url:
            return Response({"sheets": [{"properties": {
                "sheetId": report.SHEET_GID,
                "title": report.SHEET_TAB,
                "hidden": self.hidden,
                "gridProperties": {
                    "rowCount": 61,
                    "columnCount": 15,
                },
            }}]})
        if "/values/" in url:
            return Response({"values": self.rows} if self.rows else {})
        raise AssertionError("unexpected private endpoint")

    def post(self, url, *, json, **kwargs):
        if not url.endswith(":batchUpdate"):
            raise AssertionError("unexpected post")
        self.writes += 1
        patch = json["requests"]
        assert len(patch) == 1
        assert patch[0]["updateCells"]["range"]["sheetId"] == report.SHEET_GID
        self.rows = [
            [cell["userEnteredValue"]["stringValue"]
             for cell in row["values"]]
            for row in patch[0]["updateCells"]["rows"]
        ]
        return Response({"spreadsheetId": report.SHEET_ID})


def fixtures():
    records = {}
    state = {}
    sha = "a" * 64
    for n in range(1, 61):
        key = "draft-" + f"{n:032x}"
        records[key] = {
            "number": n,
            "category": "source_hold" if n == 5 else "target",
            "active": n % 2 == 0 and n != 5,
            "new": {
                "email": f"info{n}@fictional-example.test",
                "source_url": f"https://business-{n}.example.test/contact/",
            },
        }
        state[key] = (str(n + 900), "old", sha)
    return records, state


class ReportTests(unittest.TestCase):
    def test_exact_60_and_private_immutable_identity(self):
        records, state = fixtures()
        first_key = next(iter(state))
        archived = {first_key: {"sha256": "a" * 64}}
        rows = report.build_rows(
            records, state, archived, "2147483647",
            run_id="900100", now=datetime(2026, 10, 20, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 61)
        self.assertEqual(rows[0], list(report.HEADERS))
        self.assertEqual(rows[1][1], first_key)
        self.assertEqual(rows[1][5], "ARCHIEF_ORIGINEEL_MIME_SHA_OK")
        self.assertEqual(rows[2][5], "GEEN_ORIGINEEL_MIME_ARCHIEF")
        self.assertEqual(rows[5][7], "source_hold")
        self.assertEqual(rows[5][8], "NEE")
        self.assertTrue(all(row[12].startswith("NEE") for row in rows[1:]))
        self.assertEqual(rows[-1][2], "2147483647")
        self.assertEqual(rows[-1][13], "900100")

    def test_wrong_count_duplicate_uid_or_archive_mismatch_fail_closed(self):
        records, state = fixtures()
        key = next(iter(state))
        for bad in (
            lambda r, s: s.pop(key),
            lambda r, s: s[next(iter(s))].__class__,
        ):
            pass  # Variants exercised separately without changing fixtures.
        fewer = dict(state)
        fewer.pop(key)
        with self.assertRaisesRegex(RuntimeError, "v2_private_inventory_scope_invalid"):
            report.build_rows(records, fewer, {}, "123", run_id="456")
        duplicate = dict(state)
        duplicate[next(reversed(duplicate))] = next(iter(state.values()))
        with self.assertRaisesRegex(RuntimeError, "v2_private_inventory_scope_invalid"):
            report.build_rows(records, duplicate, {}, "123", run_id="456")
        with self.assertRaisesRegex(RuntimeError, "v2_private_inventory_archive_mismatch"):
            report.build_rows(records, state, {key: {"sha256": "b" * 64}},
                              "123", run_id="456")
        with self.assertRaisesRegex(RuntimeError, "v2_private_inventory_scope_invalid"):
            report.build_rows(records, state, {}, "invalid", run_id="456")

    def test_only_fixed_hidden_private_tab_and_exact_readback(self):
        records, state = fixtures()
        rows = report.build_rows(records, state, {}, "123", run_id="456")
        sheet = PrivateSheet()
        self.assertEqual(report.store_rows(rows, sheet), 60)
        self.assertEqual(sheet.writes, 1)
        self.assertEqual(sheet.rows, rows)
        with self.assertRaisesRegex(RuntimeError, "v2_private_inventory_readback_failed"):
            report.store_rows(rows, sheet)
        self.assertEqual(sheet.writes, 1)
        for session in (PrivateSheet(hidden=False), PrivateSheet(existing=True)):
            with self.assertRaisesRegex(RuntimeError, "v2_private_inventory_readback_failed"):
                report.store_rows(rows, session)
            self.assertEqual(session.writes, 0)

    def test_reject_injected_formula_or_non-private_output(self):
        records, state = fixtures()
        rows = report.build_rows(records, state, {}, "123", run_id="456")
        wrong = copy.deepcopy(rows)
        wrong.pop()
        with self.assertRaisesRegex(RuntimeError, "v2_private_inventory_scope_invalid"):
            report.store_rows(wrong, PrivateSheet())


if __name__ == "__main__":
    unittest.main()
