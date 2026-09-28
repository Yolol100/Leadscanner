from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = (
    (ROOT / ".github" / "workflows" / "leads-discovery.yml", "[lead-discovery]"),
    (ROOT / ".github" / "workflows" / "leads-discovery-overture-only.yml", "[lead-discovery-overture]"),
    (ROOT / ".github" / "workflows" / "leads-discovery-maps-only.yml", "[lead-discovery-maps]"),
)


class DiscoveryConcurrencyTests(unittest.TestCase):
    def test_unrelated_issue_events_cannot_cancel_active_discovery(self):
        for path, prefix in WORKFLOWS:
            text = path.read_text(encoding="utf-8")
            self.assertIn("github.run_id", text, path.name)
            self.assertIn("github.event_name == 'issues'", text, path.name)
            self.assertIn(f"startsWith(github.event.issue.title, '{prefix}')", text, path.name)
            self.assertIn("cancel-in-progress: true", text, path.name)


if __name__ == "__main__":
    unittest.main()
