import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import outreach_direct_smtp_runtime as d


class DirectSmtpRuntimeTests(unittest.TestCase):
    def test_no_external_verifier_required(self):
        self.assertTrue(d._no_external_verifier_required({}, None, 0))

    def test_process_replaces_external_verification_gate(self):
        original_process = d.runtime.process
        original_gate = d.runtime.verification_is_fresh
        try:
            d.runtime.process = lambda: 7
            result = d.process()
            self.assertEqual(result, 7)
            self.assertIs(d.runtime.verification_is_fresh, d._no_external_verifier_required)
        finally:
            d.runtime.process = original_process
            d.runtime.verification_is_fresh = original_gate


if __name__ == "__main__":
    unittest.main()
