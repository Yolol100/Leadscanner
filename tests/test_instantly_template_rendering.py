"""No-network two-campaign preview scenarios; never an Instantly provider render.

This simulates the documented basic Liquid if/else/endif subset only.
A real Instantly Preview with an eligible lead is still required before launch.
"""
from __future__ import annotations
import re
import unittest

from instantly_campaign_copy import campaign_steps
from instantly_client import inspect_campaign_sequence

BLOCK = re.compile(
    r"\{%\s*if\s+(?P<condition>leadscanner_observation(?:\s+and\s+leadscanner_value_action)?)\s*%\}"
    r"(?P<yes>.*?)"
    r"(?:\{%\s*else\s*%\}(?P<no>.*?))?"
    r"\{%\s*endif\s*%\}", re.S
)
PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*\}\}")

def simulate_local(text: str, variables: dict) -> str:
    def choose(match):
        conditions = match.group("condition").strip().split(" and ")
        return match.group("yes") if all(variables.get(k) for k in conditions) else (match.group("no") or "")
    reduced = BLOCK.sub(choose, text)
    def interpolate(match):
        val = variables.get(match.group(1))
        if val is None:
            raise AssertionError("fixture_required_variable_missing")
        return str(val)
    reduced = PLACEHOLDER.sub(interpolate, reduced)
    if any(marker in reduced for marker in ("{{", "}}", "{%", "%}")):
        raise AssertionError("fixture_unresolved_template")
    return reduced

class TemplateSimulation(unittest.TestCase):
    def _render(self, language: str, variables: dict) -> list[str]:
        return [simulate_local(step["variants"][0]["body"], variables)
                for step in campaign_steps(language)]

    def test_missing_verified_facts_cannot_render_followups(self):
        for language in ("nl", "en"):
            variables = {
                "leadscanner_subject": "Websitevraag",
                "leadscanner_body": "Approved subject-specific first email.",
            }
            self.assertEqual(
                simulate_local(campaign_steps(language)[0]["variants"][0]["body"], variables),
                variables["leadscanner_body"],
            )
            with self.assertRaisesRegex(AssertionError, "fixture_required_variable_missing"):
                self._render(language, variables)

    def test_new_lead_with_verified_observation_and_action(self):
        for language in ("nl", "en"):
            vars = {
                "leadscanner_subject": "Websitevraag",
                "leadscanner_body": "Approved individual lead opener.",
                "leadscanner_observation": "Verified first-party appointment route",
                "leadscanner_value_action": "a short appointment-flow sketch",
            }
            rendered = self._render(language, vars)
            self.assertIn(vars["leadscanner_observation"], rendered[1])
            self.assertIn(vars["leadscanner_value_action"], rendered[1])
            self.assertIn(vars["leadscanner_observation"], rendered[2])
            self.assertIn(vars["leadscanner_value_action"], rendered[2])
            self.assertEqual(rendered[0], vars["leadscanner_body"])

    def test_two_distinct_businesses_get_different_first_and_followup_mails(self):
        for language in ("nl", "en"):
            profiles = [
                {"leadscanner_subject": "Vraag voor een fietsenzaak",
                 "leadscanner_body": "Approved exact letter for the bike business.",
                 "leadscanner_observation": "Klanten vragen onderhoud aan via het afspraakformulier.",
                 "leadscanner_value_action": "een kort voorbeeld van de afspraakroute"},
                {"leadscanner_subject": "Vraag voor een restaurant",
                 "leadscanner_body": "Approved exact letter for the restaurant.",
                 "leadscanner_observation": "Gasten kunnen online een tafel reserveren.",
                 "leadscanner_value_action": "een kort voorbeeld van de reserveringsroute"},
            ] if language == "nl" else [
                {"leadscanner_subject": "Question for a bike shop",
                 "leadscanner_body": "Approved exact letter for the bike business.",
                 "leadscanner_observation": "Customers can request bike repairs through a form.",
                 "leadscanner_value_action": "a short example of the appointment flow"},
                {"leadscanner_subject": "Question for a restaurant",
                 "leadscanner_body": "Approved exact letter for the restaurant.",
                 "leadscanner_observation": "Guests can reserve a table online.",
                 "leadscanner_value_action": "a short example of the reservation flow"},
            ]
            first, second = (self._render(language, v) for v in profiles)
            for step_index in range(3):
                self.assertNotEqual(first[step_index], second[step_index])
                self.assertNotIn(profiles[1]["leadscanner_observation"], first[step_index])
                self.assertNotIn(profiles[0]["leadscanner_observation"], second[step_index])
            for variables, rendered in zip(profiles, (first, second)):
                self.assertEqual(rendered[0], variables["leadscanner_body"])
                self.assertIn(variables["leadscanner_observation"], rendered[1])
                self.assertIn(variables["leadscanner_value_action"], rendered[1])
                self.assertIn(variables["leadscanner_observation"], rendered[2])
                self.assertIn(variables["leadscanner_value_action"], rendered[2])
                self.assertEqual(rendered[1].count("?"), 1)
                self.assertTrue(all("Andrew Baeten" in step for step in rendered[1:]))
                self.assertTrue(all("{{" not in step for step in rendered))

    def test_partial_website_fact_cannot_render_any_followup(self):
        for language in ("nl", "en"):
            vars = {
                "leadscanner_subject": "Websitevraag",
                "leadscanner_body": "Approved first mail.",
                "leadscanner_observation": "Verified first-party appointment route",
            }
            with self.assertRaisesRegex(AssertionError, "fixture_required_variable_missing"):
                self._render(language, vars)

    def test_unknown_or_missing_variables_fail_closed(self):
        with self.assertRaisesRegex(AssertionError, "fixture_unresolved_template"):
            simulate_local("Hi {% if hidden %}private{% endif %}", {})
        with self.assertRaisesRegex(AssertionError, "fixture_required_variable_missing"):
            simulate_local("{{leadscanner_body}}", {})

    def test_three_step_structure_and_nonzero_followup_gaps(self):
        for language in ("nl", "en"):
            steps = campaign_steps(language)
            report = inspect_campaign_sequence({
                "id": "local-fixture", "status": 0,
                "sequences": [{"steps": steps}],
            })
            self.assertEqual(report["email_step_count"], 3)
            self.assertEqual(report["email_variant_count"], 3)
            self.assertFalse(report["unresolved_template_variables"])
            self.assertEqual([step["delay"] for step in steps], [4, 5, 0])

if __name__ == "__main__":
    unittest.main()
