"""Network-free QA of task-scoped 450 preparation, using fictional fixtures only."""
import copy
import os
import unittest
from unittest.mock import Mock, patch

import review450 as batch


def item(cluster=1, branch="schilders", name="Fictief Bedrijf", website="https://example.net/"):
    return {"company":name,"website":website,"email":"info@" + website.split('/')[2],
            "source_url":website,"cluster":cluster,"branche_meervoud":branch,
            "greeting":"Hoi," if cluster >= 5 else "Goedendag,",
            "status":"verified_website_and_email"}


def fixture(**kwargs):
    data = item(**kwargs)
    return batch.make_copy(data, [(data["website"], "Fictief Bedrijf schilder houtrotherstel")], "test")


class CopyQualityTests(unittest.TestCase):
    def test_six_groups_one_question_and_no_removed_intro(self):
        for cluster, branch, text in [(1,"schilders","schilder houtrotherstel"),
              (2,"kappers","kapsalon highlights"), (3,"bloemisten","bloemist boeketten"),
              (4,"garages","garage APK"), (5,"fysiotherapiepraktijken","fysiotherapie handtherapie"),
              (6,"reparatiebedrijven","fietsreparatie")]:
            with self.subTest(cluster=cluster):
                row = batch.make_copy(item(cluster, branch), [("https://example.net/",text)], "test")
                batch.validate(row)
                self.assertNotIn(batch.FORBIDDEN, row["body"])
                self.assertEqual(row["body"].count("?"), 2)
                self.assertEqual(row["body"].count(batch.OPT), 1)
                self.assertLessEqual(len(row["body"].split()),110)
                self.assertEqual(row["cluster"],str(cluster))

    def test_no_source_evidence_means_no_copy(self):
        with self.assertRaisesRegex(RuntimeError,"source_evidence"):
            batch.make_copy(item(), [("https://example.net/","unrelated content")],"test")

    def test_removed_intro_cannot_return(self):
        row = fixture()
        row["body"] = row["body"].replace("Ik help",batch.FORBIDDEN + ". Ik help")
        with self.assertRaisesRegex(RuntimeError,"copy_invalid"):
            batch.validate(row)

    def test_placeholder_and_extra_question_are_rejected(self):
        for addition in (" {{placeholder}}", " Nog een vraag?"):
            row = fixture()
            row["body"] = row["body"].replace("Groet,", addition + "\nGroet,")
            with self.assertRaises(RuntimeError):
                batch.validate(row)

    def test_broken_address_task_and_status_are_rejected(self):
        for key,value in (("email","not-an-email"),("task","another-task"),("qa_status","unchecked"),
                          ("source_url","http://127.0.0.1/"),("cluster","0")):
            with self.subTest(key=key):
                row=fixture(); row[key]=value
                with self.assertRaises(RuntimeError):
                    batch.validate(row)

    def test_random_opaque_ids_and_company_specific_subjects(self):
        a=fixture(name="Fictief Alfa")
        b=fixture(name="Fictief Beta",website="https://example.org/")
        self.assertNotEqual(a["draft_id"], b["draft_id"])
        self.assertNotEqual(a["subject"],b["subject"])
        self.assertRegex(a["draft_id"],r"^draft-[0-9a-f]{32}$")
        batch.unique([a,b])

    def test_duplicate_name_domain_email_and_id_are_blocked(self):
        a=fixture(name="Fictief Alfa")
        for key in ("company","website","email","draft_id"):
            with self.subTest(key=key):
                b=fixture(name="Fictief Beta",website="https://example.org/")
                b[key]=a[key]
                with self.assertRaises(RuntimeError):
                    batch.unique([a,b])

    def test_schema_rejects_wrong_width(self):
        with self.assertRaisesRegex(RuntimeError,"width"):
            batch.table_request(1,[["a"]],2)


class PrivateStateTests(unittest.TestCase):
    def test_history_and_batch_are_written_together_with_readback(self):
        row=fixture()
        row["run_id"]="1234567"
        history=[["first_seen_run","company","website","email","source_url","status","draft_id","recorded_at"]]
        store={"LeadHistory!A:H":history}
        def get(_conn,_sid,a1):
            return copy.deepcopy(store.get(a1,[]))
        writes=[]
        def post(_conn,requests):
            writes.append(requests)
            for req in requests:
                op=req.get("updateCells") or req.get("appendCells")
                vals=[[x.get("userEnteredValue",{}).get("stringValue","") for x in r["values"]] for r in op["rows"]]
                if "appendCells" in req:
                    store["LeadHistory!A:H"] += vals
                elif op["range"]["sheetId"] == batch.TAB_ID:
                    store[batch.TAB+"!A1:P451"] = vals
                else:
                    store[batch.STATE+"!A1:B11"] = vals
        with patch.object(batch,"read",side_effect=get),patch.object(batch,"post",side_effect=post):
            batch.state(Mock(),[row],"collecting",1,0)
        self.assertEqual(len(writes),1)
        self.assertEqual(len(writes[0]),3)
        self.assertEqual(len(store["LeadHistory!A:H"]),2)
        self.assertEqual(store[batch.TAB+"!A1:P451"][1][0],row["draft_id"])

    def test_bad_history_stops_before_any_write(self):
        with patch.object(batch,"read",return_value=[["wrong"]]),patch.object(batch,"post") as write:
            with self.assertRaises(RuntimeError):
                batch.state(Mock(),[],"collecting")
        write.assert_not_called()

    def test_missing_historical_registry_stops_public_lookups(self):
        with patch("private_candidate_handoff.authorized_writer",return_value=Mock()), \
             patch("registry_readonly.load_suppressions",side_effect=RuntimeError("unavailable")), \
             patch.object(batch,"inspect") as inspect:
            with self.assertRaises(RuntimeError):
                batch.prepare()
        inspect.assert_not_called()

    def test_unauthorized_main_cannot_execute(self):
        with patch.dict(os.environ,{"REVIEW450_PHASE":"invalid"}),patch.object(batch,"prepare") as prepare:
            self.assertEqual(batch.main(),1)
        prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
