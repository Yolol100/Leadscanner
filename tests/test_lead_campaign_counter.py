"""Read-only, no-network tests for exact campaign lead counts."""
import unittest
from unittest.mock import patch

import lead_campaign_counter as campaign
from test_verified_fill_100 import hint, approved
from verified_fill import fill_verified


SINCE = "2026-11-11T12:42:00+00:00"


def history(run, name, domain, email, stamp, status="verified_lead"):
    return [run, name, "https://" + domain + "/", email,
            "https://" + domain + "/", status, "", stamp]


def evidence(name, domain, email, status):
    row = dict.fromkeys(campaign.COLUMNS, "")
    row.update({
        "record_key": "Approved:" + campaign._digest(
            [name, "https://" + domain + "/", email])[:24],
        "source_tab": "Approved",
        "source_row": "2",
        "company": name,
        "website": "https://" + domain + "/",
        "email": email,
        "status": status,
    })
    return [row[key] for key in campaign.COLUMNS]


class CampaignCounterTests(unittest.TestCase):
    def test_only_since_cutoff_with_first_party_confirmed_counts(self):
        old = history("300", "Oud", "oud.nl", "info@oud.nl",
                      "2026-11-11T12:41:59+00:00")
        approved_one = history("400", "A", "a.nl", "info@a.nl",
                               "2026-11-11T13:00:00+00:00")
        approved_two = history("401", "B", "b.nl", "info@b.nl",
                               "2026-11-11T13:05:00+00:00")
        manual = history("402", "C", "c.nl", "info@c.nl",
                         "2026-11-11T13:06:00+00:00")
        absent = history("403", "D", "d.nl", "info@d.nl",
                         "2026-11-11T13:07:00+00:00")
        rows = [["header"] * 8, old, approved_one, approved_two, manual, absent]
        facts = [list(campaign.COLUMNS),
                 evidence("Oud", "oud.nl", "info@oud.nl", "verified_with_detail"),
                 evidence("A", "a.nl", "info@a.nl", "verified_with_detail"),
                 evidence("B", "b.nl", "info@b.nl", "verified_activity_only"),
                 evidence("C", "c.nl", "info@c.nl", "needs_manual_check")]
        connection = object()
        with patch.object(campaign, "_read_history", return_value=rows), \
             patch.object(campaign, "_read", return_value=facts) as reader:
            self.assertEqual(campaign.verified_count(SINCE, session=connection), 2)
            self.assertEqual(campaign.remaining(SINCE, goal=3, session=connection), 1)
            self.assertEqual(campaign.remaining(SINCE, goal=2, session=connection), 0)
        reader.assert_called_with(connection, campaign.EVIDENCE_RANGE)

    def test_identity_mismatch_and_duplicate_evidence_fail_closed(self):
        row = history("400", "A", "a.nl", "info@a.nl", "2026-11-11T13:00:00+00:00")
        facts = evidence("A", "a.nl", "info@a.nl", "verified_with_detail")
        changed = facts.copy()
        changed[campaign.COLUMNS.index("email")] = "info@other.nl"
        with patch.object(campaign, "_read_history",
                          return_value=[["header"] * 8, row]), \
             patch.object(campaign, "_read",
                          return_value=[list(campaign.COLUMNS), changed]):
            with self.assertRaisesRegex(RuntimeError, "campaign_identity_mismatch"):
                campaign.verified_count(SINCE, session=object())
        with patch.object(campaign, "_read_history",
                          return_value=[["header"] * 8, row]), \
             patch.object(campaign, "_read",
                          return_value=[list(campaign.COLUMNS), facts, facts]):
            with self.assertRaisesRegex(RuntimeError, "campaign_evidence_duplicate_key"):
                campaign.verified_count(SINCE, session=object())

    def test_invalid_cutoff_and_goal_block(self):
        with self.assertRaisesRegex(RuntimeError, "campaign_date_invalid"):
            campaign.verified_count("not-a-timestamp", session=object())
        with self.assertRaisesRegex(ValueError, "campaign_goal_invalid"):
            campaign.remaining(SINCE, goal=0, session=object())

    def test_exact_goal_auto_refills_across_regions_with_private_readback(self):
        import os
        import verified_fill as vf
        visited = []
        def simulate_batch():
            visited.append(os.environ["REGION"])
            return 2
        with patch.dict(os.environ, {"LEAD_AUTO_TARGET": "1",
                                    "LEAD_CAMPAIGN_GOAL": "450",
                                    "LEAD_CAMPAIGN_SINCE_UTC": SINCE}), \
             patch.object(vf, "_single", side_effect=simulate_batch), \
             patch("lead_campaign_counter.remaining", side_effect=[450, 250, 100, 0]):
            self.assertEqual(vf.main(), 0)
        self.assertEqual(visited, list(vf.AUTO_REGIONS))

    def test_partial_goal_is_successful_processing_not_fake_completion(self):
        import io
        import os
        import contextlib
        import verified_fill as vf
        output = io.StringIO()
        with patch.dict(os.environ, {"LEAD_AUTO_TARGET": "1",
                                    "LEAD_CAMPAIGN_GOAL": "450",
                                    "LEAD_CAMPAIGN_SINCE_UTC": SINCE}), \
             patch.object(vf, "_single", return_value=2) as checker, \
             patch("lead_campaign_counter.remaining", return_value=450), \
             contextlib.redirect_stdout(output):
            self.assertEqual(vf.main(), 0)
        self.assertEqual(checker.call_count, 3)
        self.assertIn('"status": "partial"', output.getvalue())
        self.assertIn('"remaining": 450', output.getvalue())

    def test_bounded_verified_batch_accepts_small_last_target(self):
        result = fill_verified("Rotterdam", ["vakbedrijven"], 30, target=2,
            discoverer=lambda **kwargs: {"candidates": [hint(i) for i in range(5)]},
            verifier=approved, load_registry=lambda: [])
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["approved"]), 2)
        self.assertEqual(result["target"], 2)


if __name__ == "__main__":
    unittest.main()
