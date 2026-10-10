"""No-network regression tests for verified Draft/Paused no-sender routing."""
import unittest
from unittest.mock import patch
from copy import deepcopy
from instantly_campaign_copy import campaign_steps

from instantly_language_route import preflight_campaign, route_exact_language
from instantly_language_campaigns import LANGUAGE_CAMPAIGN_NAMES

CID="5c720281-fd07-4c47-8155-c88d7d3c09b8"
LID="24deb187-59e0-43b5-86b8-fe37a7b21e2a"
NAME=LANGUAGE_CAMPAIGN_NAMES["nl"]
SUBJECT="idee voor jullie afspraakroute"
OBSERVATION="Klanten kunnen online een afspraak aanvragen voor onderhoud of reparatie."
ACTION="een korte voorbeeldvariant voor de afspraakroute"
BODY=("Hoi, op jullie website zag ik dit: " + OBSERVATION
      + "\\n\\nAls je wilt, kan ik " + ACTION
      + " maken. Zal ik een voorbeeld toesturen?"
      + "\\n\\nGeen interesse, laat het gerust weten; dan stop ik."
      + "\\n\\nGroet,\\nAndrew Baeten").replace("\\n", "\n")
ROW={"id":"11111111-1111-1111-1111-111111111111","email":"contact@example.org","list_id":LID,"campaign":None,
"payload":{"leadscanner_import_origin":"myhost_drafts","leadscanner_contact_basis":"consent_verified","leadscanner_contact_basis_ref":"verified-proof-2026","leadscanner_source_lead_id":"growth-"+"a"*20,
"leadscanner_subject":SUBJECT,"leadscanner_body":BODY,
"leadscanner_observation":OBSERVATION,
"leadscanner_value_action":ACTION,
"leadscanner_evidence_url":"https://example.org/afspraak",
"leadscanner_evidence_source_type":"official_site"}}
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
        api.campaign["status"]=2
        preflight_campaign(api,"nl",CID)
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

    def test_exact_copy_into_paused_campaign_without_senders_never_sends(self):
        api=Fake()
        api.campaign["status"]=2
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)
        self.assertEqual(report["confirmed_copied_count"],1)
        self.assertEqual(report["eligible_candidate_count"],1)
        self.assertFalse(report["automatic_send"])
        self.assertFalse(report["campaign_activated"])
        self.assertEqual(api.campaign["status"],2)
        self.assertEqual(api.campaign["email_list"],[])

    def test_dry_run_with_verified_eligible_lead_never_writes(self):
        api=Fake()
        api.campaign["status"]=2
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1,dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["eligible_candidate_count"],1)
        self.assertEqual(report["attempt_count"],0)
        self.assertEqual(report["confirmed_copied_count"],0)
        self.assertEqual(api.calls,[])
        self.assertEqual(api.destination,[])

    def test_paused_audit_holds_unverified_permission(self):
        api=Fake()
        api.campaign["status"]=2
        row=dict(ROW,payload=dict(ROW["payload"],leadscanner_contact_basis="review_required"))
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[row])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1,dry_run=True)
        self.assertEqual(report["eligible_candidate_count"],0)
        self.assertEqual(report["held_counts"]["contact_basis_hold"],1)
        self.assertFalse(api.calls)

    def test_rejects_unreviewed_or_ambiguous_sender_identity(self):
        api=Fake()
        bad=dict(ROW,payload={**ROW["payload"],"leadscanner_body":
                   "Hoi, ik zag de website. Laat het weten als dit passend is. Groet, Andrew."})
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[bad])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1,dry_run=True)
        self.assertEqual(report["held_counts"]["sender_identity_hold"],1)
        self.assertEqual(report["eligible_candidate_count"],0)
        self.assertFalse(api.calls)

    def test_active_completed_boolean_or_sender_assigned_fail_before_any_lead_read(self):
        api=Fake()
        for bad_status in (1,3,-1,True,None):
            api.campaign["status"]=bad_status
            with self.subTest(status=bad_status),self.assertRaisesRegex(ValueError,"must_be_draft_or_paused"):
                preflight_campaign(api,"nl",CID)
        api.campaign["status"]=2
        api.campaign["email_list"]=["sender@example.org"]
        with self.assertRaisesRegex(ValueError,"no_senders"):
            preflight_campaign(api,"nl",CID)
        self.assertFalse(api.calls)

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

    def test_imported_legacy_sender_brand_cannot_be_staged(self):
        api=Fake()
        bad=dict(ROW,payload={**ROW["payload"],
                   "leadscanner_body":"Hoi. Groet, Andrew van "+"Web"+"actueel."})
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[bad])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)
        self.assertEqual(report["held_counts"]["obsolete_sender_brand_hold"],1)
        self.assertEqual(report["attempt_count"],0)
        self.assertFalse(api.calls)

    def test_imported_lead_without_website_provenance_cannot_route(self):
        api=Fake()
        no_evidence=dict(ROW, payload={
            k:v for k,v in ROW["payload"].items()
            if k not in {"leadscanner_observation","leadscanner_value_action",
                         "leadscanner_evidence_url","leadscanner_evidence_source_type"}
        })
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[no_evidence])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1)
        self.assertEqual(report["attempt_count"],0)
        self.assertEqual(report["held_counts"]["personalization_evidence_hold"],1)
        self.assertFalse(api.calls)

    def test_duplicate_first_mail_pair_is_held_for_both_recipients(self):
        api=Fake()
        other=deepcopy(ROW)
        other["id"]="22222222-2222-2222-2222-222222222222"
        other["email"]="second@example.org"
        other["payload"]["leadscanner_source_lead_id"]="growth-"+"b"*20
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW,other])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            result=route_exact_language(api,language="nl",campaign_id=CID,max_leads=2,dry_run=True)
        self.assertEqual(result["eligible_candidate_count"],0)
        self.assertEqual(result["held_counts"]["duplicate_first_mail_copy_hold"],2)
        self.assertEqual(result["attempt_count"],0)
        self.assertFalse(api.calls)
        self.assertNotIn(BODY,str(result))
        self.assertNotIn(other["email"],str(result))

    def test_same_subject_with_genuinely_different_first_mail_is_not_deduped(self):
        api=Fake()
        other=deepcopy(ROW)
        other["id"]="22222222-2222-2222-2222-222222222222"
        other["email"]="second@example.org"
        other["payload"]["leadscanner_source_lead_id"]="growth-"+"b"*20
        second_fact="Gasten kunnen online een tafel reserveren via het formulier."
        second_action="een korte voorbeeldvariant voor de reserveringsroute"
        other["payload"]["leadscanner_observation"]=second_fact
        other["payload"]["leadscanner_value_action"]=second_action
        other["payload"]["leadscanner_body"]=BODY.replace(
            OBSERVATION, second_fact).replace(ACTION, second_action)
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW,other])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            result=route_exact_language(api,language="nl",campaign_id=CID,max_leads=2,dry_run=True)
        self.assertEqual(result["held_counts"]["duplicate_first_mail_copy_hold"],0)
        self.assertEqual(result["eligible_candidate_count"],2)
        self.assertEqual(result["attempt_count"],0)
        self.assertFalse(api.calls)

    def test_name_swap_only_first_mail_is_held_despite_verified_fact_fields(self):
        api=Fake()
        generic=deepcopy(ROW)
        generic["payload"]["leadscanner_body"]=(
            "Hoi Bedrijf A, ik bekeek jullie website. "
            "Ik heb een interessant idee. Zal ik dit toesturen?"
            "\\n\\nGeen interesse is prima.\\n\\nGroet,\\nAndrew Baeten"
        ).replace("\\n","\n")
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[generic])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1,dry_run=True)
        self.assertEqual(report["eligible_candidate_count"],0)
        self.assertEqual(report["held_counts"]["first_mail_not_recipient_specific_hold"],1)
        self.assertEqual(report["attempt_count"],0)
        self.assertFalse(api.calls)

    def test_reused_website_observation_is_held_even_with_different_messages(self):
        api=Fake()
        other=deepcopy(ROW)
        other["id"]="22222222-2222-2222-2222-222222222222"
        other["email"]="another@different-company.example.org"
        other["payload"]["leadscanner_source_lead_id"]="growth-"+"b"*20
        other["payload"]["leadscanner_body"]=BODY.replace(
            "Hoi, op jullie website zag ik dit:",
            "Goedemorgen, op jullie website viel me het volgende op:")
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[ROW,other])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=2,dry_run=True)
        self.assertEqual(report["eligible_candidate_count"],0)
        self.assertEqual(report["held_counts"]["reused_website_observation_hold"],2)
        self.assertFalse(api.calls)
        self.assertNotIn(OBSERVATION,str(report))

    def test_weak_observation_is_not_sufficient_personalization(self):
        api=Fake()
        item=deepcopy(ROW)
        weak="Wij zijn een familiebedrijf met veel ervaring."
        item["payload"]["leadscanner_observation"]=weak
        item["payload"]["leadscanner_body"]=BODY.replace(OBSERVATION,weak)
        with patch("instantly_language_route.read_imported_leads",return_value=(LID,[item])),\
             patch("instantly_language_route.fetch_live_registry",return_value=[]),\
             patch("instantly_language_route.blocked_values",return_value=set()):
            report=route_exact_language(api,language="nl",campaign_id=CID,max_leads=1,dry_run=True)
        self.assertEqual(report["held_counts"]["first_mail_not_recipient_specific_hold"],1)
        self.assertEqual(report["attempt_count"],0)
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
