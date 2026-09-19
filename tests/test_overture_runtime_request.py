import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_overture_discovery_request import load_request, run


class RuntimeDiscoveryRequestTests(unittest.TestCase):
    def write_request(self, data):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, handle)
        handle.close()
        return Path(handle.name)

    def valid_request(self):
        return {
            "request_id": "overture-test-001",
            "enabled": True,
            "region": "Rotterdam",
            "radius_km": 8,
            "keywords": ["bakery", "baker"],
            "max_results": 10,
            "require_website": True,
            "probe_websites": True,
        }

    def test_valid_request(self):
        path = self.write_request(self.valid_request())
        try:
            result = load_request(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(result["region"], "Rotterdam")
        self.assertIsNone(result["bbox"])
        self.assertEqual(result["max_results"], 10)

    def test_region_and_bbox_are_mutually_exclusive(self):
        data = self.valid_request()
        data["bbox"] = "4.3,51.8,4.7,52.1"
        path = self.write_request(data)
        try:
            with self.assertRaises(ValueError):
                load_request(path)
        finally:
            path.unlink(missing_ok=True)

    def test_max_results_is_bounded_to_100(self):
        data = self.valid_request()
        data["max_results"] = 101
        path = self.write_request(data)
        try:
            with self.assertRaises(ValueError):
                load_request(path)
        finally:
            path.unlink(missing_ok=True)

    def test_keywords_are_bounded(self):
        data = self.valid_request()
        data["keywords"] = [f"k{i}" for i in range(13)]
        path = self.write_request(data)
        try:
            with self.assertRaises(ValueError):
                load_request(path)
        finally:
            path.unlink(missing_ok=True)

    @patch("run_overture_discovery_request.discover")
    def test_run_is_non_authorizing(self, discover):
        discover.return_value = {
            "candidate_count": 1,
            "privacy_and_scope": {
                "contact_basis_evaluated": False,
                "draftqueue_write": False,
                "email_send": False,
            },
            "candidates": [
                {
                    "overture_id": "x",
                    "identity_status": "needs_leads_verification",
                }
            ],
        }
        request = self.write_request(self.valid_request())
        output = Path(tempfile.mkstemp(suffix=".json")[1])
        try:
            result = run(request, output)
            written = json.loads(output.read_text(encoding="utf-8"))
        finally:
            request.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

        self.assertEqual(result["runtime_transport"], "temporary_git_branch")
        self.assertEqual(written["request_id"], "overture-test-001")
        self.assertFalse(written["privacy_and_scope"]["contact_basis_evaluated"])
        self.assertFalse(written["privacy_and_scope"]["draftqueue_write"])
        self.assertFalse(written["privacy_and_scope"]["email_send"])


if __name__ == "__main__":
    unittest.main()
