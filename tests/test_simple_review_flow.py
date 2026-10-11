"""One simple prospect-review flow from sourced findings to exact approval."""
import csv
import io
import unittest
from copy import deepcopy

from outreach_stages import (
    draft_for_review, generate_one_mail, generate_sequence_facts,
    review_findings, select_one_reason, value_action_for,
)
from review_draft_stages import prepare_review_batch
from review_selection import build_review_queue, render_csv, render_markdown, review_token, select_approved


def _source(text, path):
    return {
        "text": text,
        "source_type": "official_site",
        "source_url": f"https://sample.nl/{path}",
        "page_type": "process",
    }


def _candidate():
    return {
        "name_hint": "Voorbeeldwinkel",
        "official_domain": "sample.nl",
        "official_url": "https://sample.nl/",
        "public_business_email": "info@sample.nl",
        "research_status": "ready",
        "evidence_candidates": [
            _source("Klanten kunnen online een afspraak aanvragen voor onderhoud.", "afspraak"),
            _source("Vraag online een offerte aan via ons formulier voor maatwerk.", "offerte"),
            _source("Klanten kunnen online bestellen met afhalen in onze winkel.", "bestellen"),
            _source("Onze klanten vinden antwoorden in de kennisbank met veelgestelde vragen.", "hulp"),
            _source("Bekijk onze projecten met praktijkvoorbeelden van gerealiseerde installaties.", "projecten"),
        ],
    }


def _selected():
    selected = select_one_reason(_candidate())
    valued = value_action_for(selected)
    assert len(valued["selected_findings"]) >= 4
    return valued


class SimpleReviewFlowTests(unittest.TestCase):
    def test_same_email_renderer_for_new_and_historical_review(self):
        data = _selected()
        first = generate_one_mail(data)
        self.assertEqual(first["mail_status"], "ready_for_human_review")
        subject, body = draft_for_review(
            data["verified_observation"], data["value_first_action"],
            data["signal_type"], data["language"], data["selected_findings"],
        )
        self.assertEqual(first["subject"], subject)
        self.assertEqual(first["body"], body)
        self.assertEqual(body.count("?"), 1)
        self.assertIn("Andrew Baeten", body)

    def test_quoted_website_question_does_not_count_as_extra_email_question(self):
        data = _selected()
        observation = "Kunnen klanten online een afspraak aanvragen voor onderhoud?"
        source_url = data["selected_findings"][0]["source_url"]
        data["selected_findings"] = [{
            "category": "appointment", "priority": "high", "score": 110,
            "observation": observation, "source_url": source_url,
            "source_type": "official_site", "page_type": "process",
        }]
        data["verified_observation"] = observation
        data["verified_observation_source_url"] = source_url
        review = generate_one_mail(data)
        self.assertEqual(review["mail_status"], "ready_for_human_review")
        self.assertEqual(review["body"].count("?"), 2)
        self.assertFalse(review["copy_validation_reasons"])

    def test_all_findings_reach_queue_with_exact_token_binding(self):
        mail = generate_one_mail(_selected())
        batch = prepare_review_batch({"candidates": [mail]})
        row = batch["rows"][0]
        queue = build_review_queue(batch)
        point_count = len(mail["selected_findings"])
        self.assertGreaterEqual(point_count, 4)
        self.assertLessEqual(point_count, 6)
        self.assertEqual(row["selected_findings"], mail["selected_findings"])
        self.assertEqual(queue["items"][0]["findings_count"], point_count)
        self.assertEqual(queue["items"][0]["selected_findings"], mail["selected_findings"])
        self.assertIn("Belangrijkste bevindingen", render_markdown(queue))
        self.assertIn(mail["selected_findings"][0]["source_url"], render_markdown(queue))
        csv_row = next(csv.DictReader(io.StringIO(render_csv(queue))))
        self.assertEqual(int(csv_row["findings_count"]), point_count)
        token = queue["items"][0]["approval_token"]
        self.assertEqual(select_approved(batch, token)["approval"]["approved_count"], 1)
        altered = deepcopy(batch)
        altered["rows"][0]["selected_findings"][1]["observation"] += " extra tekst"
        with self.assertRaisesRegex(ValueError, "unknown_or_stale_approval_token"):
            select_approved(altered, token)

    def test_fact_only_review_keeps_evidence_without_drafting_mail(self):
        facts = generate_sequence_facts({"candidates": [_selected()]})
        self.assertEqual(facts["ready_for_human_review_count"], 1)
        row = prepare_review_batch(facts)["rows"][0]
        self.assertEqual(row["review_mode"], "instantly_sequence")
        self.assertEqual(row["body"], "")
        self.assertGreaterEqual(len(row["selected_findings"]), 4)
        queue = build_review_queue({"rows": [row]})
        self.assertEqual(queue["items"][0]["selected_findings"], row["selected_findings"])
        self.assertNotIn("### Body", render_markdown(queue))

    def test_rejects_outside_site_malformed_markup_and_duplicate_evidence(self):
        valid = _selected()["selected_findings"]
        for bad in (
            dict(valid[0], source_url="https://outside.example/page"),
            dict(valid[0], observation="{{other_template}}"),
            dict(valid[0], source_type="directory"),
            dict(valid[0], source_url="https://sample.nl@other.example/"),
            dict(valid[0], source_url="javascript:alert(1)"),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                review_findings([bad], "sample.nl")
        with self.assertRaises(ValueError):
            review_findings([valid[0], valid[0]], "sample.nl")
        with self.assertRaises(ValueError):
            review_findings(valid + valid, "sample.nl")

    def test_modified_review_findings_cannot_be_smuggled_into_queue(self):
        mail = generate_one_mail(_selected())
        mail["selected_findings"][2]["source_url"] = "https://other.example/page"
        with self.assertRaisesRegex(ValueError, "review_findings_require_verified_official_site"):
            prepare_review_batch({"candidates": [mail]})

    def test_old_reviews_without_findings_still_work(self):
        older = generate_one_mail(value_action_for(select_one_reason({
            **_candidate(),
            "evidence_candidates": _candidate()["evidence_candidates"][:1],
        })))
        older.pop("selected_findings")
        batch = prepare_review_batch({"candidates": [older]})
        self.assertEqual(batch["rows"][0]["selected_findings"], [])
        token = review_token(batch["rows"][0])
        self.assertEqual(select_approved(batch, token)["approval"]["approved_count"], 1)


if __name__ == "__main__":
    unittest.main()
