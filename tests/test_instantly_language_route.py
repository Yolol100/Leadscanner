"""No-network regression tests for safe draft-only language routing."""
import unittest
from unittest.mock import patch
from copy import deepcopy
from instantly_campaign_copy import campaign_steps

from instantly_language_route import preflight_campaign, route_exact_language
from instantly_language_campaigns import LANGUAGE_CAMPAIGN_NAMES

CID="5c720281-fd07-4c47-8155-c88d7d3c09b8"
LID="24deb187-59e0-43b5-86b8-fe37a7b21e2a"
NAME=LANGUAGE_CAMPAIGN_NAMES["nl"]
SUBJECT="Een korte vraag over jullie website"
BODY="Hoi, ik zag jullie website en dacht aan een klein idee. Laat gerust weten als je graag een voorstel wilt."
ROW={"id":"11111111-1111-1111-1111-111111111111","email":"contact@example.org","list_id":LID,"campaign":None,
"payload":{"leadscanner_import_origin":"myhost_drafts","leadscanner_contact_basis":"consent_verified","leadscanner_contact_basis_ref":"verified-proof-2026","leadscanner_source_lead_id":"growth-"+"a"*20,
"leadscanner_subject":SUBJECT,"leadscanner_body":BODY}}
SEQUENCE={"steps":campaign_steps("nl")}


class Fake:
    def __init__(self):
        self.sent=False
        self.destination=[]
        self.calls=[]
        self.campaign={"id":CID,"name":NAME,"status":0,"email_list":[],
                       "sequences":[deepcopy(SEQUENCE)],"stop_on_reply":True,"allow_risky_contacts":False}
    def get_campaign(self, cid):
        return self.campaign
    def list_leads(self, *, campaign=None, limit=100, starting_after=None, **kwargs):
        if campaign: return {"items":self.destination,"next_starting_after":None}
        raise AssertionError("unsupported list")
    def _request(self, method,path,**kwargs):
        self.calls.append((method,path))
        if path=="/leads/move":
            self.destination=[dict(ROW, campaign=CID)]
            return {"id":"22222222-2222-2222-2222-222222222222"}
        if path.startswith("/background-jobs/"):
            return {"status":"completed"}
        raise AssertionError(path)


class TestLanguageRouting(unittest.TestCase):
    def test_provider_status_is_safe_and_preserved(self):
        from instantly_client import InstantlyError
        from instantly_language_route import _step
        with self.assertRaisesRegex(RuntimeError, "^routing_stage_blocklist_InstantlyError_http404$"):
            _step("blocklist", lambda: (_ for _ in ()).throw(InstantlyError("instantly_api_error status=404")))

    def test_stage_label_redacts_connection_details(self):
        from instantly_language_route import _step

        def fail():
            raise RuntimeError("contains private test email person@example.org")
        with self.assertRaisesRegex(RuntimeError, "^routing_stage_source_list_RuntimeError$") as ctx:
            _step("source_list", fail)
        self.assertNotIn("person@example.org", str(ctx.exception))

    def test_preflight_rejects_active_and_sender_assigned(self):
        api=Fake()
        preflight_campaign(api,"nl",CID)
        api.campaign["status"]=1
        with self.assertRaisesRegex(ValueError,"must_be_draft"):
            preflight_campaign(api,"nl",CID)
        api.campaign["status"]=0
        api.campaign["email_list"]=["connected@example.org"]
        with self.assertRaisesRegex(ValueError,"no_senders"):
            preflight_campaign(api,"nl",CID)

    def test_legacy_language_copy_rejects_unreviewed_followup_drift(self):
        api=Fake()
        api.campaign["sequences"][0]["steps"][1]["variants"][0]["body"] += " Newly added claim."
        with self.assertRaisesRegex(ValueError,"routing_campaign_copy_readback_mismatch"):
            preflight_campaign(api,"nl",CID)

    def test_exact_copy_into_draft_never_sends(self):
        api=Fake()
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)
        self.assertEqual(report["confirmed_copied_count"],1)
        self.assertFalse(report["campaign_activated"])
        self.assertFalse(report["automatic_send"])
        self.assertFalse(report["original_list_modified"])
        self.assertEqual(api.calls,[("POST","/leads/move"),("GET","/background-jobs/22222222-2222-2222-2222-222222222222")])

    def test_ambiguous_or_existing_lead_skipped(self):
        api=Fake();api.destination=[dict(ROW,campaign=CID)]
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)
        self.assertEqual(report["already_present_count"],1)
        self.assertEqual(report["attempt_count"],0)
        self.assertFalse(api.calls)

    def test_unverified_contact_basis_must_not_be_copied(self):
        api=Fake()
        row=dict(ROW, payload=dict(ROW["payload"],leadscanner_contact_basis="review_required"))
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[row])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            out=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)
        self.assertEqual(out["held_counts"]["contact_basis_hold"],1)
        self.assertEqual(out["attempt_count"],0)
        self.assertFalse(api.calls)

    def test_wrong_target_id_language_and_size_fail_before_provider(self):
        api=Fake()
        for language,cid,size in [("de",CID,1),("nl","notuuid",1),("nl",CID,0),("nl",CID,251)]:
            with self.assertRaises(ValueError):
                route_exact_language(api,language=language,campaign_id=cid,max_leads=size)
        self.assertFalse(api.calls)

    def test_copy_rejected_if_no_matching_email_after_job(self):
        api=Fake()
        api._request=lambda method,path,**kw: {"id":"22222222-2222-2222-2222-222222222222"} if method=="POST" else {"status":"completed"}
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            with self.assertRaisesRegex(RuntimeError,"destination_readback_missing"):
                route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)



    def test_parent_domain_blocklist_prevents_subdomain_routing(self):
        api=Fake()
        row=dict(ROW,email="contact@sub.example.org")
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[row])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value={"example.org"}):
            result=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)
        self.assertEqual(result["held_counts"]["blocklist_hold"],1)
        self.assertEqual(result["attempt_count"],0)
        self.assertFalse(api.calls)


if __name__=="__main__":
    unittest.main()
