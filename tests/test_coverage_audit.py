import unittest

from coverage_audit import build_coverage


class CoverageAuditTests(unittest.TestCase):
    def request(self, *, target=30, verify=20):
        return {
            "region": "Rotterdam",
            "keywords": ["schilder"],
            "target_candidates": target,
            "verify_limit": verify,
            "radius_km": 10,
        }

    def test_sufficient_buffer_does_not_add_second_source(self):
        result = build_coverage(
            request=self.request(),
            raw={"candidate_count": 40},
            filtered={"candidate_count": 35},
            dedupe={"kept_count": 28},
        )
        self.assertEqual(result["source_status"], "sufficient_buffer")
        self.assertEqual(result["second_source_decision"], "second_source_not_needed")
        self.assertFalse(result["rules"]["second_source_auto_added"])

    def test_thin_source_broadens_query_before_second_source(self):
        result = build_coverage(
            request=self.request(),
            raw={"candidate_count": 12},
            filtered={"candidate_count": 11},
            dedupe={"kept_count": 10},
        )
        self.assertEqual(result["source_status"], "thin")
        self.assertEqual(result["second_source_decision"], "broaden_query_before_second_source")

    def test_gap_requires_repeat_evidence(self):
        result = build_coverage(
            request=self.request(),
            raw={"candidate_count": 4},
            filtered={"candidate_count": 4},
            dedupe={"kept_count": 4},
        )
        self.assertEqual(result["source_status"], "gap")
        self.assertEqual(result["second_source_decision"], "repeat_gap_check_before_second_source")
        self.assertTrue(result["rules"]["require_repeated_independent_gap_evidence"])

    def test_target_below_verify_limit_is_config_limited(self):
        result = build_coverage(
            request=self.request(target=10, verify=20),
            raw={"candidate_count": 10},
            filtered={"candidate_count": 10},
            dedupe={"kept_count": 10},
        )
        self.assertEqual(result["source_status"], "measurement_config_limited")
        self.assertEqual(result["second_source_decision"], "increase_target_before_second_source")


if __name__ == "__main__":
    unittest.main()
