"""Synthetic-only regression for anonymous historical runner diagnostics."""
import contextlib
from io import StringIO
import sys
import unittest
from unittest.mock import patch

from _once_historical_site_redraft import main, safe_failure_marker


class SafeHistoricFailureTests(unittest.TestCase):
    def test_sensitive_exception_text_is_never_reflected(self):
        try:
            raise ValueError("PRIVATE email contact@confidential.invalid https://private.example/")
        except ValueError as error:
            marker = safe_failure_marker(error)
        self.assertIn("type=value_error", marker)
        self.assertIn("origin=unclassified", marker)
        self.assertNotIn("confidential", marker)
        self.assertNotIn("private.example", marker)
        self.assertNotIn("@", marker)

    def test_main_hides_private_failure_and_does_not_retry_or_send(self):
        marker = "PRIVATE email contact@confidential.invalid full mail subject"
        output = StringIO()
        with patch.object(sys, "argv", ["historical", "--offset", "1000", "--mode", "audit"]):
            with patch("_once_historical_site_redraft.run",
                       side_effect=RuntimeError(marker)) as run_mock:
                with contextlib.redirect_stdout(output):
                    status = main()
        self.assertEqual(status, 1)
        run_mock.assert_called_once_with(1000, "audit")
        line = output.getvalue()
        self.assertIn("HISTORICAL_SITE_REBUILD=red", line)
        self.assertIn("stage=private_failure_hold", line)
        self.assertIn("type=runtime_error", line)
        self.assertNotIn(marker, line)
        self.assertNotIn("@", line)
        self.assertNotIn("http", line)


if __name__ == "__main__":
    unittest.main()
