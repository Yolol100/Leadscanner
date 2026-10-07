import tempfile
import unittest
from pathlib import Path

from instantly_audit import evaluate


class InstantlyAuditTests(unittest.TestCase):
    def test_current_repository_static_audit_is_full_green(self):
        root = Path(__file__).resolve().parents[1]
        result = evaluate(root)
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["static_score"], "9/9")
        failed = [check["name"] for check in result["checks"] if not check["ok"]]
        self.assertEqual(failed, [])
        self.assertTrue(result["runtime_point_requires_ci_and_live_smoke"])


if __name__ == "__main__":
    unittest.main()
