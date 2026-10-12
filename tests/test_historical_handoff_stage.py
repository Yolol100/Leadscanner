"""Never-sending historical Instantly campaign staging regression tests."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from historical_handoff_stage import (
    EXPECTED_REVIEWED, TARGET_CAMPAIGNS, build_destination_variables,
    stage_batch, _update_destination, safe_failure_code,
    await_destination_copies, COPY_VISIBILITY_DELAYS,
)
from historical_handoff_audit import _reviewed_refresh
from tests.test_historical_handoff_audit import row
from myhost_instantly_import import TARGET_LIST_ID


def source_rows():
    result = [
        row(i, status="candidate_review_required") for i in range(776)
    ] + [row(i, status="research_only_contact_unverified") for i in range(776, 1128)]
    for item in result:
        item["list_id"] = TARGET_LIST_ID
        item["payload"]["leadscanner_import_origin"] = "myhost_drafts"
    return result


class FakeClient:
    def __init__(self, rows):
        self.sources = {r["id"]: deepcopy(r) for r in rows}
        self.destinations = {}
        self.posts = []
        self.patches = []

    def get_lead(self, lead_id):
        return deepcopy(self.sources.get(lead_id) or self.destinations[lead_id])

    def list_leads(self, *, campaign, limit, starting_after=None):
        if starting_after:
            raise AssertionError("only first page in this fake")
        matches = [
            deepcopy(r) for r in self.destinations.values()
            if r.get("campaign") == campaign
        ]
        if len(matches) > 100:
            raise AssertionError("not part of synthetic pagination test")
        return {"items": matches, "next_starting_after": ""}

    def _request(self, method, path, *, json=None):
        if method == "POST" and path == "/leads/move":
            self.posts.append(deepcopy(json))
            for src_id in json["ids"]:
                src = self.sources[src_id]
                lead_id = "dest-" + src_id
                self.destinations[lead_id] = {
                    **deepcopy(src),
                    "id": lead_id,
                    "list_id": None,
                    "campaign": json["to_campaign_id"],
                }
            return {"id": "background-fake-job-00001"}
        if method == "PATCH" and path.startswith("/leads/"):
            self.patches.append((path, deepcopy(json)))
            lead_id = path.removeprefix("/leads/")
            self.destinations[lead_id]["payload"] = deepcopy(json["custom_variables"])
            return {}
        raise AssertionError("unexpected provider mutation")


class PausedHandoffStageTests(unittest.TestCase):
    def test_destination_handoff_copy_only_changes_destination_and_preserves_consent_status(self):
        src = source_rows()[0]
        dest = deepcopy(src)
        dest["id"] = "new-copy"
        dest["campaign"] = TARGET_CAMPAIGNS["nl"][0]
        before = deepcopy(src)
        updated = build_destination_variables(src, dest)
        self.assertEqual(src, before)
        self.assertEqual(updated["leadscanner_subject"], src["payload"]["leadscanner_site_refresh_subject"])
        self.assertEqual(updated["leadscanner_body"], src["payload"]["leadscanner_site_refresh_body"])
        self.assertEqual(updated["leadscanner_contact_basis"], "review_required")
        self.assertEqual(updated["leadscanner_handoff_status"], "reviewed_staged_no_send")
        self.assertEqual(len(updated["leadscanner_handoff_content_sha256"]), 64)
        self.assertNotEqual(updated["leadscanner_body"], src["payload"].get("leadscanner_body"))

    def test_first_batch_copies_100_into_paused_targets_preserving_1128_source_leads(self):
        rows = source_rows()
        original = deepcopy(rows)
        client = FakeClient(rows)
        registry_payloads = []
        def registry_write(readback, **_kw):
            registry_payloads.extend(readback["registry_rows"])
            return {"exact_readback": True}
        with patch("historical_handoff_stage._source_rows", return_value=rows), \
             patch("historical_handoff_stage.fetch_live_registry", return_value=[]), \
             patch("historical_handoff_stage.blocked_values", return_value=set()), \
             patch("historical_handoff_stage.preflight_campaign"), \
             patch("historical_handoff_stage.check_registry_access"), \
             patch("historical_handoff_stage._wait_job"), \
             patch("historical_handoff_stage.update_registry", side_effect=registry_write):
            result = stage_batch(client, offset=0)
            self.assertEqual(result["counts"]["destination_personalization_confirmed"], 100)
            self.assertEqual(result["counts"]["destination_updated"], 100)
            self.assertEqual(result["counts"]["registry_verified"], 100)
            self.assertEqual(len(client.posts), 10)
            self.assertTrue(all(post["copy_leads"] for post in client.posts))
            self.assertTrue(all(len(post["ids"]) <= 10 for post in client.posts))
            self.assertEqual(sum(len(post["ids"]) for post in client.posts), 100)
            self.assertEqual(len(client.patches), 100)
            self.assertEqual(len(client.sources), 1128)
            self.assertEqual(rows, original)
            self.assertEqual(len(registry_payloads), 100)
            self.assertTrue(all(x[-1] == "TRUE" for x in registry_payloads))
            self.assertEqual(result["email_sent"], 0)
            self.assertFalse(result["campaign_activation"])
            # Retry must reconcile copies and not duplicate provider move.
            retry = stage_batch(client, offset=0)
            self.assertEqual(len(client.posts), 10)
            self.assertEqual(len(client.patches), 100)
            self.assertEqual(retry["counts"]["destination_personalization_confirmed"], 100)

    def test_one_lead_smoke_then_full_cohort_is_idempotent_and_non_sending(self):
        rows = source_rows()
        client = FakeClient(rows)
        with patch("historical_handoff_stage._source_rows", return_value=rows), \
             patch("historical_handoff_stage.fetch_live_registry", return_value=[]), \
             patch("historical_handoff_stage.blocked_values", return_value=set()), \
             patch("historical_handoff_stage.preflight_campaign"), \
             patch("historical_handoff_stage.check_registry_access"), \
             patch("historical_handoff_stage._wait_job"), \
             patch("historical_handoff_stage.update_registry", return_value={"exact_readback": True}):
            smoke = stage_batch(client, offset=0, max_targets=1)
            self.assertEqual(smoke["counts"]["destination_personalization_confirmed"], 1)
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(len(client.patches), 1)
            self.assertFalse(smoke["campaign_activation"])
            full = stage_batch(client, offset=0)
            self.assertEqual(full["counts"]["destination_personalization_confirmed"], 100)
            self.assertEqual(full["counts"]["destination_updated"], 99)
            self.assertEqual(len(client.posts), 11)
            self.assertEqual(len(client.destinations), 100)
            self.assertEqual(len(client.sources), 1128)

    def test_partial_copy_is_personalized_before_new_move_and_resume_is_idempotent(self):
        rows = source_rows()
        client = FakeClient(rows)
        prior = deepcopy(rows[0])
        prior["id"] = "dest-" + rows[0]["id"]
        prior["campaign"] = TARGET_CAMPAIGNS["nl"][0]
        prior["list_id"] = None
        client.destinations[prior["id"]] = prior
        sequence = []
        original_request = client._request
        def traced_request(method, path, *, json=None):
            sequence.append((method, path))
            return original_request(method, path, json=json)
        client._request = traced_request
        with patch("historical_handoff_stage._source_rows", return_value=rows), \
             patch("historical_handoff_stage.fetch_live_registry", return_value=[]), \
             patch("historical_handoff_stage.blocked_values", return_value=set()), \
             patch("historical_handoff_stage.preflight_campaign"), \
             patch("historical_handoff_stage.check_registry_access"), \
             patch("historical_handoff_stage._wait_job"), \
             patch("historical_handoff_stage.update_registry", return_value={"exact_readback": True}):
            stage_batch(client, offset=0)
            self.assertEqual(sequence[0][0], "PATCH")
            self.assertTrue(all(len(p["ids"]) <= 10 for p in client.posts))
            self.assertEqual(len(client.destinations), 100)
            self.assertEqual(len(client.patches), 100)
            self.assertEqual(sum(len(p["ids"]) for p in client.posts), 99)
            again = stage_batch(client, offset=0)
            self.assertEqual(again["counts"].get("destination_updated", 0), 0)
            self.assertEqual(len(client.patches), 100)
            self.assertEqual(sum(len(p["ids"]) for p in client.posts), 99)

    def test_unknown_background_job_status_requires_complete_destination_readback(self):
        rows = source_rows()
        client = FakeClient(rows)
        with patch("historical_handoff_stage._source_rows", return_value=rows), \
             patch("historical_handoff_stage.fetch_live_registry", return_value=[]), \
             patch("historical_handoff_stage.blocked_values", return_value=set()), \
             patch("historical_handoff_stage.preflight_campaign"), \
             patch("historical_handoff_stage.check_registry_access"), \
             patch("historical_handoff_stage._wait_job", side_effect=RuntimeError("routing_background_job_unknown_status")), \
             patch("historical_handoff_stage.update_registry", return_value={"exact_readback": True}):
            report = stage_batch(client, offset=0)
        self.assertEqual(report["counts"]["job_status_reconciled_by_destination"], 10)
        self.assertEqual(report["counts"]["destination_personalization_confirmed"], 100)
        self.assertEqual(report["counts"]["registry_verified"], 100)
        self.assertEqual(len(client.posts), 10)
        self.assertEqual(len(client.patches), 100)
        self.assertEqual(report["email_sent"], 0)

    def test_reported_failed_background_job_never_implicitly_succeeds(self):
        rows = source_rows()
        client = FakeClient(rows)
        with patch("historical_handoff_stage._source_rows", return_value=rows), \
             patch("historical_handoff_stage.fetch_live_registry", return_value=[]), \
             patch("historical_handoff_stage.blocked_values", return_value=set()), \
             patch("historical_handoff_stage.preflight_campaign"), \
             patch("historical_handoff_stage.check_registry_access"), \
             patch("historical_handoff_stage._wait_job", side_effect=RuntimeError("routing_background_job_failed")):
            with self.assertRaisesRegex(RuntimeError, "routing_background_job_failed"):
                stage_batch(client, offset=0)
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(client.patches, [])

    def test_async_completed_copy_is_polled_until_destination_is_visible(self):
        src = source_rows()[0]
        client = FakeClient([src])
        dest = deepcopy(src)
        dest["id"] = "dest-" + src["id"]
        dest["list_id"] = None
        dest["campaign"] = TARGET_CAMPAIGNS["nl"][0]
        client.destinations[dest["id"]] = dest
        original_list = client.list_leads
        attempts = []
        def lagged_list(*, campaign, limit, starting_after=None):
            attempts.append(1)
            if len(attempts) <= 2:
                return {"items": [], "next_starting_after": ""}
            return original_list(campaign=campaign, limit=limit, starting_after=starting_after)
        client.list_leads = lagged_list
        sleeps = []
        result = await_destination_copies(
            client, TARGET_CAMPAIGNS["nl"][0],
            {src["email"]}, sleep_fn=sleeps.append,
        )
        self.assertIn(src["email"], result)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [1, 2])
        self.assertEqual(client.posts, [])
        self.assertEqual(client.patches, [])

    def test_async_copy_not_visible_exits_without_blind_retry(self):
        client = FakeClient([])
        sleeps = []
        with self.assertRaisesRegex(
            RuntimeError, "historical_handoff_copied_lead_visibility_unconfirmed"
        ):
            await_destination_copies(
                client, TARGET_CAMPAIGNS["nl"][0],
                {"not-visible@example.org"}, sleep_fn=sleeps.append,
            )
        self.assertEqual(tuple(sleeps), COPY_VISIBILITY_DELAYS)
        self.assertEqual(client.posts, [])
        self.assertEqual(client.patches, [])

    def test_copy_visibility_requires_exact_nonempty_recipient_set(self):
        with self.assertRaisesRegex(ValueError, "expected_copy_set_empty"):
            await_destination_copies(FakeClient([]), TARGET_CAMPAIGNS["nl"][0], set())

    def test_existing_approved_destination_copy_cannot_be_silently_changed(self):
        src = source_rows()[0]
        dest = deepcopy(src)
        dest["id"] = "dest-row-0"
        dest["list_id"] = None
        dest["campaign"] = TARGET_CAMPAIGNS["nl"][0]
        dest["payload"] = build_destination_variables(src, dest)
        dest["payload"]["leadscanner_body"] += " unapproved changed content"
        client = FakeClient([src])
        client.destinations[dest["id"]] = dest
        with self.assertRaisesRegex(RuntimeError, "already_staged_copy_changed"):
            _update_destination(client, src, dest, TARGET_CAMPAIGNS["nl"][0])
        self.assertEqual(client.patches, [])

    def test_source_changed_or_active_campaign_prevents_provider_move(self):
        rows = source_rows()
        client = FakeClient(rows)
        client.sources["row-0"]["payload"]["leadscanner_site_refresh_body"] += " changed"
        with patch("historical_handoff_stage._source_rows", return_value=rows), \
             patch("historical_handoff_stage.fetch_live_registry", return_value=[]), \
             patch("historical_handoff_stage.blocked_values", return_value=set()), \
             patch("historical_handoff_stage.preflight_campaign"), \
             patch("historical_handoff_stage.check_registry_access"):
            with self.assertRaisesRegex(RuntimeError, "source_changed_before_copy"):
                stage_batch(client, offset=0)
        self.assertEqual(client.posts, [])
        with patch("historical_handoff_stage._source_rows", return_value=rows), \
             patch("historical_handoff_stage.fetch_live_registry", return_value=[]), \
             patch("historical_handoff_stage.blocked_values", return_value=set()), \
             patch("historical_handoff_stage.preflight_campaign", side_effect=ValueError("campaign active")), \
             patch("historical_handoff_stage.check_registry_access"):
            with self.assertRaisesRegex(ValueError, "campaign active"):
                stage_batch(FakeClient(rows), offset=0)

    def test_public_error_diagnostic_does_not_leak_provider_details(self):
        self.assertEqual(
            safe_failure_code(RuntimeError("historical_handoff_copied_lead_missing")),
            "historical_handoff_copied_lead_missing",
        )
        self.assertEqual(
            safe_failure_code(RuntimeError("person@example.org confidential content")),
            "runtime_unknown",
        )
        self.assertEqual(
            safe_failure_code(ValueError("private?token=secret")),
            "value_contract",
        )

    def test_invalid_offset_or_cohort_aborts_without_provider_read(self):
        fake = FakeClient([])
        for offset, reviewed in ((1, EXPECTED_REVIEWED), (-100, EXPECTED_REVIEWED), (0, 777)):
            with self.subTest(offset=offset, reviewed=reviewed):
                with self.assertRaises(ValueError):
                    stage_batch(fake, offset=offset, expected_reviewed=reviewed)


if __name__ == "__main__":
    unittest.main()
