from __future__ import annotations

import unittest

from instantly_private_request import (
    PrivateRequestError,
    _clip_json,
    _json_field,
    _require_request_id,
)


class PrivateRequestTests(unittest.TestCase):
    def test_request_id_is_opaque_and_bounded(self):
        self.assertEqual(_require_request_id("instantly-20260915-001"), "instantly-20260915-001")
        with self.assertRaises(PrivateRequestError):
            _require_request_id("contains space")
        with self.assertRaises(PrivateRequestError):
            _require_request_id("")

    def test_json_field_parses_or_blocks(self):
        self.assertEqual(_json_field('{"limit":1}', "query_json", default={}), {"limit": 1})
        self.assertEqual(_json_field("", "query_json", default={}), {})
        with self.assertRaises(PrivateRequestError):
            _json_field("{bad", "query_json", default={})

    def test_private_result_cells_are_bounded(self):
        rendered = _clip_json({"body": "x" * 100_000})
        self.assertLessEqual(len(rendered), 45_000)
        self.assertIn("TRUNCATED", rendered)


if __name__ == "__main__":
    unittest.main()
