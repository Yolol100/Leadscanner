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

if __name__=="__main__":
    unittest.main()
