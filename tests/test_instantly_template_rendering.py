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

    def test_legacy_copy_without_verified_extra_facts(self):
        for language in ("nl", "en"):
            variables = {
                "leadscanner_subject": "Websitevraag",
                "leadscanner_body": "Approved subject-specific first email."
            }
            steps = self._render(language, variables)
            self.assertEqual(steps[0], variables["leadscanner_body"])
            self.assertTrue(all(step.strip() for step in steps))
            if language == "nl":
                self.assertIn("als eerste", steps[1])
                self.assertIn("laatste bericht", steps[2])
            else:
                self.assertIn("first 2", steps[1])
                self.assertIn("last note", steps[2])
            self.assertNotIn("Verified first-party", "\n".join(steps))

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
            self.assertEqual(rendered[0], vars["leadscanner_body"])

    def test_partial_fact_uses_generic_second_step_but_specific_third(self):
        for language in ("nl", "en"):
            vars = {
                "leadscanner_subject": "Websitevraag",
                "leadscanner_body": "Approved first mail.",
                "leadscanner_observation": "Verified first-party appointment route",
            }
            rendered = self._render(language, vars)
            self.assertNotIn(vars["leadscanner_observation"], rendered[1])
            self.assertIn(vars["leadscanner_observation"], rendered[2])

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
