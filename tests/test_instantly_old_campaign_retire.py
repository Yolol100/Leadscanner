"""No-network preservation contract: no old campaign deletes before safe archive."""
import unittest
from instantly_old_campaign_retire import (
    archive_and_retire_old_campaign,CAMPAIGN_ID,CAMPAIGN_NAME,ARCHIVE_NAME,
)
from instantly_client import InstantlyError
LIST_ID="22222222-2222-2222-2222-222222222222"
OLD_ID="11111111-1111-1111-1111-111111111111"
LEAD={"id":OLD_ID,"email":"old@example.org","payload":{"note":"keep"}}

class Fake:
    def __init__(self):
        self.deleted=False
        self.archive=[]
        self.calls=[]
        self.status=2
        self.history=[]
    def get_campaign(self,cid):
        if self.deleted: raise InstantlyError("instantly_api_error status=404")
        return {"id":cid,"name":CAMPAIGN_NAME,"status":self.status}
    def list_leads(self,*,campaign=None,list_id=None,contacts=None,limit=100,starting_after=None):
        return {"items":[LEAD] if campaign else list(self.archive)}
    def get_emails(self,**kwargs):
        return {"items":self.history}
    def _request(self,method,path,**kwargs):
        self.calls.append((method,path))
        if (method,path)==("GET","/lead-lists"):
            return {"items":[{"id":LIST_ID,"name":ARCHIVE_NAME}]}
        if (method,path)==("POST","/leads/move"):
            self.archive=[{"id":"33333333-3333-3333-3333-333333333333",
                           "email":LEAD["email"],"list_id":LIST_ID,"payload":LEAD["payload"]}]
            return {"id":"44444444-4444-4444-4444-444444444444"}
        if (method,path)==("GET","/background-jobs/44444444-4444-4444-4444-444444444444"):
            return {"status":"completed"}
        if (method,path)==("DELETE","/campaigns/"+CAMPAIGN_ID):
            self.deleted=True;return {}
        raise AssertionError(f"unexpected {method} {path}")

class Tests(unittest.TestCase):
    def test_safe_copy_then_delete(self):
        f=Fake()
        result=archive_and_retire_old_campaign(f)
        self.assertTrue(result["old_campaign_deleted"])
        self.assertTrue(result["lead_copied_on_this_run"])
        self.assertEqual(result["source_leads_archived"],1)
        self.assertFalse(result["email_sent"])
        self.assertNotIn("old@example.org",str(result))
        self.assertLess(f.calls.index(("POST","/leads/move")),f.calls.index(("DELETE","/campaigns/"+CAMPAIGN_ID)))
    def test_source_cursor_with_single_lead_is_enumerated_safely(self):
        class Cursor(Fake):
            def list_leads(self,*,campaign=None,list_id=None,contacts=None,limit=100,starting_after=None):
                if campaign==CAMPAIGN_ID:
                    if not starting_after:
                        return {"items":[LEAD],"next_starting_after":"cursor-2"}
                    if starting_after=="cursor-2":
                        return {"items":[],"next_starting_after":None}
                return {"items":list(self.archive),"next_starting_after":None}
        f=Cursor()
        out=archive_and_retire_old_campaign(f)
        self.assertTrue(out["old_campaign_deleted"])
        self.assertTrue(f.deleted)

    def test_archive_readback_last_nonempty_page_may_have_cursor(self):
        from instantly_old_campaign_retire import _archive_leads
        class Cursor(Fake):
            def list_leads(self,*,campaign=None,list_id=None,contacts=None,limit=100,starting_after=None):
                if list_id:
                    if starting_after=="terminal":
                        return {"items":[],"next_starting_after":None}
                    return {"items":[{"id":"33333333-3333-3333-3333-333333333333",
                                     "email":LEAD["email"],"list_id":LIST_ID,
                                     "payload":LEAD["payload"]}],
                            "next_starting_after":"terminal"}
                return {"items":[LEAD]}
        result=_archive_leads(Cursor(),LIST_ID,LEAD["email"])
        self.assertEqual(len(result),1)

    def test_archive_refuses_wrong_list_even_if_email_matches(self):
        from instantly_old_campaign_retire import _archive_leads
        class Wrong(Fake):
            def list_leads(self,*,campaign=None,list_id=None,contacts=None,limit=100,starting_after=None):
                return {"items":[{"email":LEAD["email"],"list_id":"wrong"}]}
        with self.assertRaisesRegex(RuntimeError,"archive_readback_identity_mismatch"):
            _archive_leads(Wrong(),LIST_ID,LEAD["email"])

    def test_archive_metadata_audit_counts_without_exposing_values(self):
        from instantly_old_campaign_retire import audit_old_archive_metadata
        f=Fake()
        f.archive=[{"id":"33333333-3333-3333-3333-333333333333",
                   "email":LEAD["email"],"list_id":LIST_ID,"payload":{}}]
        report=audit_old_archive_metadata(f)
        self.assertEqual(report["missing_field_count"],1)
        self.assertEqual(report["conflicting_field_count"],0)
        self.assertFalse(report["writes"])
        self.assertNotIn("keep",str(report))
        self.assertNotIn("old@example.org",str(report))

    def test_stop_if_email_history(self):
        f=Fake();f.history=[{"id":"email"}]
        with self.assertRaisesRegex(ValueError,"email_history"):
            archive_and_retire_old_campaign(f)
        self.assertFalse(f.deleted)
        self.assertEqual(f.calls,[])
    def test_stop_if_campaign_active(self):
        f=Fake();f.status=1
        with self.assertRaisesRegex(ValueError,"paused_campaign"):
            archive_and_retire_old_campaign(f)
        self.assertFalse(f.deleted)
    def test_stop_if_copy_does_not_preserve_custom_fields(self):
        f=Fake()
        f.archive=[{"id":"33333333-3333-3333-3333-333333333333",
                    "email":LEAD["email"],"list_id":LIST_ID,"payload":{"note":"DIFFERENT"}}]
        with self.assertRaisesRegex(RuntimeError,"custom_fields_changed"):
            archive_and_retire_old_campaign(f)
        self.assertFalse(f.deleted)
if __name__=="__main__":
    unittest.main()
