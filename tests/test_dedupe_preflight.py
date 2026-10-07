import csv
import json
import tempfile
import unittest
from pathlib import Path

from dedupe_preflight import normalize_company, normalize_domain, run


HEADERS = [
    "company",
    "website",
    "domain",
    "emails",
    "status",
    "history",
    "lead_ids",
    "last_event_at",
    "sources",
    "exclude_from_new_leads",
]


class DedupePreflightTests(unittest.TestCase):
    def write_registry(self, root: Path, rows: list[list[str]]) -> Path:
        path = root / "registry.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS)
            writer.writerows(rows)
        return path

    def run_case(self, rows, candidates):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = self.write_registry(root, rows)
            candidate_path = root / "candidates.json"
            output = root / "out.json"
            candidate_path.write_text(json.dumps(candidates), encoding="utf-8")
            return run(registry, candidate_path, output)

    def test_company_normalization_is_exact_but_format_tolerant(self):
        self.assertEqual(normalize_company("Acme B.V."), normalize_company("ACME BV"))
        self.assertNotEqual(normalize_company("Acme Noord"), normalize_company("Acme Zuid"))

    def test_domain_normalization_strips_www_and_path(self):
        self.assertEqual(normalize_domain("https://www.example.nl/contact"), "example.nl")

    def test_excludes_by_company_domain_email_and_lead_id(self):
        rows = [[
            "Acme B.V.",
            "https://www.acme.nl/",
            "acme.nl",
            "info@acme.nl; sales@acme.nl",
            "concept",
            "concept",
            "growth-acme-1",
            "",
            "Leadlijst",
            "TRUE",
        ]]
        candidates = [
            {"name_hint": "ACME BV"},
            {"website_hint": "https://shop.acme.nl/product"},
            {"email": "sales@acme.nl"},
            {"lead_id": "GROWTH-ACME-1"},
            {"company": "Nieuwe Firma", "website": "https://nieuw.nl"},
        ]
        result = self.run_case(rows, candidates)
        self.assertEqual(result["excluded_count"], 4)
        self.assertEqual(result["kept_count"], 1)
        self.assertEqual(result["kept"][0]["company"], "Nieuwe Firma")

    def test_false_registry_rows_do_not_exclude(self):
        rows = [[
            "Acme",
            "https://acme.nl",
            "acme.nl",
            "info@acme.nl",
            "concept",
            "",
            "lead-1",
            "",
            "",
            "FALSE",
        ], [
            "Keep Registry Alive",
            "https://keep.nl",
            "keep.nl",
            "info@keep.nl",
            "concept",
            "",
            "lead-keep",
            "",
            "",
            "TRUE",
        ]]
        result = self.run_case(rows, [{"company": "Acme", "website": "https://acme.nl"}])
        self.assertEqual(result["excluded_count"], 0)
        self.assertEqual(result["kept_count"], 1)

    def test_fails_closed_for_missing_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "registry.csv"
            registry.write_text("company,domain\nAcme,acme.nl\n", encoding="utf-8")
            candidates = root / "candidates.json"
            candidates.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "registry_missing_headers"):
                run(registry, candidates, root / "out.json")

    def test_fails_closed_for_candidate_without_identity(self):
        rows = [[
            "Existing",
            "https://existing.nl",
            "existing.nl",
            "info@existing.nl",
            "concept",
            "",
            "lead-existing",
            "",
            "",
            "TRUE",
        ]]
        with self.assertRaisesRegex(ValueError, "candidate_without_identity"):
            self.run_case(rows, [{"category_hint": "schilder"}])


if __name__ == "__main__":
    unittest.main()
