from pathlib import Path
import json
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

    def test_toolkit_versions_match_package_dependencies(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        contract = json.loads((ROOT / "toolkit-contract.json").read_text(encoding="utf-8"))
        tools = {item["id"]: item["version"] for item in contract["scanner_tools"]}
        expected = {
            "crawlee": package["dependencies"]["crawlee"],
            "playwright": package["dependencies"]["playwright"],
            "axe-core": package["dependencies"]["@axe-core/playwright"],
            "linkinator": package["dependencies"]["linkinator"],
            "lighthouse": package["dependencies"]["lighthouse"],
        }
        self.assertEqual(expected, {key: tools[key] for key in expected})


if __name__ == "__main__":
    unittest.main()
