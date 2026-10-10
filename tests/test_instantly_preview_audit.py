"""Live campaign templates rendered only with invented recipient fixtures."""
import copy
import unittest

from instantly_campaign_copy import TARGET_CAMPAIGNS, campaign_steps
from instantly_preview_audit import (
    audit_synthetic_campaign_previews, render_synthetic,
)
from instantly_control import execute_command


class FakeProvider:
    def __init__(self):
        self.campaigns = {
            cid: {
                "id": cid, "name": name, "status": 2, "email_list": [],
                "sequences": [{"steps": campaign_steps(language)}],
            }
            for language, (cid, name) in TARGET_CAMPAIGNS.items()
        }
        self.leads = set()
        self.reads = 0

    def get_campaign(self, cid):
        self.reads += 1
        return copy.deepcopy(self.campaigns[cid])

    def list_leads(self, *, campaign=None, limit=100, starting_after=None):
        self.reads += 1
        return {
            "items": [{"id": "not-a-real-lead"}] if campaign in self.leads else [],
            "next_starting_after": None,
        }

    def _request(self, *args, **kwargs):
        raise AssertionError("synthetic_audit_must_never_write")


class TestSyntheticLiveCampaignPreview(unittest.TestCase):
    def test_twelve_synthetic_renders_of_six_live_messages_have_no_real_contacts(self):
        provider = FakeProvider()
        result = audit_synthetic_campaign_previews(provider)
        self.assertTrue(result["all_checks_passed"])
        self.assertEqual(result["synthetic_profiles_checked"], 4)
        self.assertEqual(result["rendered_email_bodies_checked"], 12)
        self.assertEqual([item["rendered_email_bodies_checked"]
                          for item in result["campaigns"]], [6, 6])
        self.assertFalse(result["provider_ui_preview_performed"])
        self.assertFalse(result["real_contact_data_used"])
        self.assertFalse(result["writes"])
        self.assertFalse(result["sends"])
        self.assertEqual(provider.reads, 4)
        result_text = str(result)
        for protected in ("Customers can request bike repairs",
                          "Klanten kunnen via het fietsafspraakformulier",
                          "andrewbaeten.nl", "synthetic@example.org"):
            self.assertNotIn(protected, result_text)

    def test_live_campaign_must_remain_paused_with_no_senders_and_no_leads(self):
        cid = TARGET_CAMPAIGNS["nl"][0]
        for field, value in (
            ("status", 1),
            ("status", 0),
            ("status", True),
            ("email_list", ["info@example.org"]),
            ("name", "Incorrect campaign"),
            ("id", "incorrect-id"),
        ):
            provider = FakeProvider()
            provider.campaigns[cid][field] = value
            with self.subTest(field=field,value=value):
                with self.assertRaisesRegex(RuntimeError,"exact_paused_campaign"):
                    audit_synthetic_campaign_previews(provider)
        provider = FakeProvider()
        provider.leads.add(cid)
        with self.assertRaisesRegex(RuntimeError,"empty_campaign"):
            audit_synthetic_campaign_previews(provider)

    def test_copy_mutation_is_rejected_before_rendering(self):
        provider = FakeProvider()
        cid = TARGET_CAMPAIGNS["en"][0]
        provider.campaigns[cid]["sequences"][0]["steps"][1]["variants"][0]["body"] = (
            "Hi, this is an unrelated generic line."
        )
        with self.assertRaisesRegex(RuntimeError,"exact_paused_campaign"):
            audit_synthetic_campaign_previews(provider)

    def test_renderer_rejects_liquid_unknown_merges_and_missing_facts(self):
        for source, variables, error in (
            ("{% if secret %}private{% endif %}", {}, "liquid_not_supported"),
            ("{{unknown}}", {"unknown": "secret"}, "unexpected_merge_variable"),
            ("{{leadscanner_observation}}", {}, "required_fact_missing"),
            ("{{leadscanner_subject}}", {"leadscanner_subject": "{{unresolved}}"}, "unresolved_or_unescaped"),
        ):
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError,error):
                    render_synthetic(source, variables)
        self.assertEqual(render_synthetic("subject {{leadscanner_subject}}",
                                         {"leadscanner_subject": "example"}),
                         "subject example")

    def test_readonly_control_action_runs_with_write_gate_disabled(self):
        client=FakeProvider()
        command={
            "schema_version":"leadscanner-instantly-command/1.0",
            "command_id":"audit-synthetic-nl-en-001",
            "action":"audit_synthetic_campaign_previews",
            "args":{},
            "requested_by":"chatgpt",
        }
        settings={
            "schema_version":"leadscanner-instantly-control/1.0",
            "write_actions_enabled":False,
            "send_actions_enabled":False,
            "destructive_actions_enabled":False,
            "require_exact_confirmation":True,
        }
        result=execute_command(command, settings, client)
        self.assertEqual(result["status"],"green")
        self.assertTrue(result["result"]["all_checks_passed"])
        self.assertFalse(result["result"]["writes"])


if __name__ == "__main__":
    unittest.main()
