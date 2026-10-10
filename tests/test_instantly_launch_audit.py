"""No-network audit tests: no sender or recipient details in artifacts."""
import unittest
from unittest.mock import patch

from instantly_launch_audit import audit_launch_inventory, _permission_counts, TARGETS

NL=TARGETS["nl"]
EN=TARGETS["en"]
class Fake:
    def __init__(self):
        self.calls=[]
    def list_campaigns(self,limit=100,starting_after=None):
        return {"items":[{"id":NL},{"id":EN},{"id":"old"}]}
    def get_campaign(self,cid):
        return {"id":cid,"name":"Safe" if cid in {NL,EN} else "old",
                "status":0,"email_list":[]}
    def list_leads(self,campaign=None,limit=100,starting_after=None):
        if campaign=="old":
            return {"items":[{"email":"do.not.expose@example.org"}]}
        return {"items":[]}
    def _request(self,method,path,**kwargs):
        self.calls.append((method,path))
        return {"items":[{"email":"sender.do.not.expose@example.org","status":1,
                          "warmup_status":"active","health_score":98}]}

class Tests(unittest.TestCase):
    def test_audit_aggregate_never_exposes_lead_or_sender_emails(self):
        f=Fake()
        with patch("instantly_launch_audit.blocked_values",return_value={"bad@example.org"}),\
             patch("instantly_launch_audit.read_imported_leads",return_value=("source",[
             {"payload":{"leadscanner_contact_basis":"review_required"}},
             {"payload":{"leadscanner_contact_basis":"consent_verified","leadscanner_contact_basis_ref":"proof-2026-01"}},
            ])):
            r=audit_launch_inventory(f)
        self.assertEqual(r["source_contact_basis"]["unverified_or_review_required"],1)
        self.assertEqual(r["source_contact_basis"]["documented_eligible"],1)
        self.assertEqual(r["other_campaign_count"],1)
        self.assertEqual(r["active_account_count"],1)
        self.assertEqual(r["blocklist"]["entry_count"],1)
        self.assertFalse(r["go_live_approved"])
        self.assertFalse(r["old_campaign_delete_approved"])
        self.assertNotIn("do.not.expose@example.org",str(r))
        self.assertNotIn("sender.do.not.expose@example.org",str(r))
        self.assertNotIn("bad@example.org",str(r))

    def test_vitals_collects_only_aggregate_domain_results(self):
        from instantly_launch_audit import audit_sender_vitals
        class Vitals(Fake):
            def _request(self, method, path, **kwargs):
                if path=="/accounts/test/vitals":
                    self.assertion_body=kwargs["json"]
                    return {"status":"success","success_list":[{"domain":"private.example","allPass":True}],"failure_list":[]}
                return super()._request(method,path,**kwargs)
        f=Vitals()
        out=audit_sender_vitals(f)
        self.assertEqual(out["account_count"],1)
        self.assertEqual(out["vitals_allpass_count"],1)
        self.assertEqual(out["active_connection_count"],1)
        self.assertIn("sender.do.not.expose@example.org",f.assertion_body["accounts"])
        self.assertNotIn("sender.do.not.expose@example.org",str(out))
        self.assertFalse(out["ready_to_send"])

    def test_old_campaign_retirement_must_preserve_unique_lead_or_history(self):
        from instantly_launch_audit import audit_old_campaign_retirement, OLD_ACTIVE_CAMPAIGN
        class Old(Fake):
            def get_campaign(self,cid):
                if cid==OLD_ACTIVE_CAMPAIGN:return {"id":cid,"status":2}
                return super().get_campaign(cid)
            def list_leads(self,campaign=None,**kwargs):
                if campaign==OLD_ACTIVE_CAMPAIGN:
                    return {"items":[{"email":"old@company.example"}]}
                return {"items":[]}
            def get_emails(self,**kwargs):
                return {"items":[{"id":"historical"}]}
        api=Old()
        with patch("instantly_launch_audit.read_imported_leads",return_value=("source",[])):
            result=audit_old_campaign_retirement(api)
        self.assertFalse(result["eligible_for_delete"])
        self.assertTrue(result["historical_email_activity_present"])
        self.assertEqual(result["duplicate_in_safe_source_count"],0)
        self.assertNotIn("old@company.example",str(result))

    def test_blocklist_api_error_kind_has_no_provider_payload(self):
        from instantly_client import InstantlyError
        with patch("instantly_launch_audit.blocked_values",
                   side_effect=InstantlyError("instantly_network_error")):
            out=audit_launch_inventory(Fake(),source=False)
        self.assertEqual(out["blocklist"]["cause"],"network")
        self.assertIsNone(out["blocklist"]["http_status"])
        self.assertFalse(out["go_live_approved"])

    def test_two_campaign_settings_audit_distinguishes_missing_from_verified(self):
        from instantly_launch_audit import audit_two_campaign_options, TARGETS
        class Scenario(Fake):
            def get_campaign(self,cid):
                return {
                    "id":cid,"status":0,"email_list":[],
                    "daily_limit":10,"daily_max_leads":5,"email_gap":12,
                    "stop_on_reply":True,"open_tracking":False,
                    "campaign_schedule":{"schedules":[{
                        "timezone":"Arctic/Longyearbyen",
                        "timing":{"from":"09:30","to":"16:30"},
                        "days":{"1":True,"2":True,"3":True,"4":True,"5":True},
                    }]},
                }
        report=audit_two_campaign_options(Scenario())
        self.assertEqual(len(report["campaigns"]),2)
        self.assertFalse(report["all_confirmed_settings_match"])
        self.assertGreater(report["campaigns"][0]["not_returned_count"],0)
        self.assertFalse(report["sends"])
        self.assertNotIn("sender.do.not.expose@example.org",str(report))

    def test_missing_contact_proof_remains_unverified(self):
        self.assertEqual(_permission_counts([
            {"payload":{"leadscanner_contact_basis":"consent_verified"}},
            {"payload":{"leadscanner_contact_basis":"review_required","leadscanner_contact_basis_ref":"proof-2026"}},
        ]),{"unverified_or_review_required":2})

    def test_provider_missing_accounts_fail_closed(self):
        class Bad(Fake):
            def _request(self,*args,**kwargs):return {"items":[]}
        with patch("instantly_launch_audit.blocked_values",return_value=set()):
            out=audit_launch_inventory(Bad(),source=False)
        self.assertEqual(out["active_account_count"],0)
        self.assertFalse(out["go_live_approved"])


    def test_campaign_audit_fails_closed_on_changed_schedule_or_copy(self):
        from instantly_launch_audit import audit_two_campaign_options
        from instantly_campaign_copy import campaign_steps
        class Provider(Fake):
            def __init__(self, drift):
                super().__init__()
                self.drift=drift
            def get_campaign(self,cid):
                lang=next(x for x,y in TARGETS.items() if y==cid)
                steps=campaign_steps(lang)
                if self.drift=="copy" and lang=="nl":
                    steps[1]["variants"][0]["body"]+=" Unreviewed text."
                timing={"from":"09:30","to":"16:30"}
                if self.drift=="schedule" and lang=="nl":
                    timing["from"]="00:00"
                status={"paused":2,"active":1,"boolean":True}.get(self.drift,0)
                senders=["sender@example.org"] if self.drift=="sender" else []
                return {"id":cid,"status":status,"email_list":senders,"sequences":[{"steps":steps}],
                    "daily_limit":10,"daily_max_leads":5,"email_gap":12,
                    "stop_on_reply":True,"stop_on_auto_reply":True,"stop_for_company":True,
                    "allow_risky_contacts":False,"open_tracking":False,"link_tracking":False,
                    "text_only":True,"insert_unsubscribe_header":True,
                    "campaign_schedule":{"schedules":[{"timezone":"Arctic/Longyearbyen",
                        "timing":timing,"days":{"0":False,"1":True,"2":True,"3":True,
                            "4":True,"5":True,"6":False}}]}}
        good=audit_two_campaign_options(Provider("none"))
        self.assertTrue(good["all_confirmed_settings_match"])
        self.assertTrue(good["all_reviewed_copy_matches"])
        paused=audit_two_campaign_options(Provider("paused"))
        self.assertTrue(paused["all_confirmed_settings_match"])
        self.assertTrue(paused["all_reviewed_copy_matches"])
        self.assertTrue(all(item["paused"] and item["non_sending_staging_state"]
                            and not item["draft"] for item in paused["campaigns"]))
        for bad_state in ("active","boolean","sender"):
            with self.subTest(bad_state=bad_state):
                unsafe=audit_two_campaign_options(Provider(bad_state))
                self.assertFalse(unsafe["all_confirmed_settings_match"])

        schedule=audit_two_campaign_options(Provider("schedule"))
        self.assertFalse(schedule["all_confirmed_settings_match"])
        copy=audit_two_campaign_options(Provider("copy"))
        self.assertFalse(copy["all_reviewed_copy_matches"])

if __name__=="__main__":
    unittest.main()
