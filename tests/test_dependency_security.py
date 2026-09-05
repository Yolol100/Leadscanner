from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DependencySecurityTests(unittest.TestCase):
    def test_dependabot_covers_all_runtime_dependency_ecosystems(self):
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        for ecosystem in ("npm", "pip", "github-actions"):
            self.assertIn(f"package-ecosystem: {ecosystem}", text)

    def test_python_runtime_ci_checks_consistency_and_known_vulnerabilities(self):
        text = (ROOT / ".github" / "workflows" / "leads-runtime-ci.yml").read_text(encoding="utf-8")
        self.assertIn("python3 -m pip check", text)
        self.assertIn("pip-audit==2.10.1", text)
        self.assertIn("python3 -m pip_audit --requirement requirements-outreach.txt", text)


if __name__ == "__main__":
    unittest.main()
