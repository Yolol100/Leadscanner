"""Privacy and prioritization regressions for the active Leadscanner pipeline."""
import unittest
from pathlib import Path
from outreach_stages import select_one_reason

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "leads-cold.yml"


def sourced(sentence, route):
    return {
        "source_type": "official_site",
        "source_url": f"https://voorbeeld.nl/{route}",
        "page_type": "process",
        "text": sentence,
    }


class PrivacyAndRankingTests(unittest.TestCase):
    def test_public_repo_privacy_gate_precedes_research_and_artifact_upload(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        execute = source[source.index("  execute:\n"):source.index("  instantly_control:\n")]
        self.assertIn("REPOSITORY_IS_PRIVATE: ${{ github.event.repository.private }}", execute)
        self.assertLess(
            execute.index("Require private repository for prospect artifacts"),
            execute.index("Install preview runtime"),
        )
        self.assertLess(
            execute.index("Require private repository for prospect artifacts"),
            execute.index("Validate request"),
        )
        self.assertIn('if [ "$REPOSITORY_IS_PRIVATE" != \'true\' ]; then', execute)
        self.assertIn("exit 1", execute[:execute.index("Install preview runtime")])
        self.assertIn("results/review-queue.md", execute)
        self.assertIn("results/preview-snapshot.json", execute)

    def test_public_repo_instantly_command_result_gate_is_before_execution(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        control = source[source.index("  instantly_control:\n"):source.index("  instantly_sync:\n")]
        self.assertIn("REPOSITORY_IS_PRIVATE: ${{ github.event.repository.private }}", control)
        self.assertLess(
            control.index("Block Instantly command artifacts in public repository"),
            control.index("Execute only newly-added immutable Instantly commands"),
        )
        self.assertIn(
            'if [ -s results/new-instantly-command-paths.txt ] && [ "$REPOSITORY_IS_PRIVATE" != \'true\' ]; then',
            control,
        )
        self.assertIn("exit 1", control)

    def test_public_or_empty_command_run_never_uploads_an_artifact(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        control = source[source.index("  instantly_control:\n"):source.index("  instantly_sync:\n")]
        self.assertIn("id: new_commands", control)
        self.assertIn("echo 'has_commands=false' >> \"$GITHUB_OUTPUT\"", control)
        self.assertIn(
            "if: always() && steps.new_commands.outputs.has_commands == 'true' && github.event.repository.private == true",
            control,
        )

    def test_six_stronger_observations_are_not_displaced_by_weak_category(self):
        strong = [
            ("Klanten kunnen online een afspraak maken voor de jaarlijkse onderhoudsbeurt.", "one"),
            ("Onze klanten kunnen online een afspraak aanvragen voor de bandenservice.", "two"),
            ("Maak een afspraak voor onderhoud aan zakelijke machines via onze website.", "three"),
            ("Plan een afspraak voor reparaties aan uw elektrische fiets online.", "four"),
            ("Boek eenvoudig een afspraak voor de fietsencontrole op locatie.", "five"),
            ("Vraag vandaag een afspraak aan voor montage en nazorg bij ons.", "six"),
        ]
        evidence = [sourced(t, p) for t, p in strong]
        evidence.append(sourced(
            "Bekijk onze projecten met praktijkvoorbeelden van gerealiseerde installaties.",
            "portfolio",
        ))
        result = select_one_reason({
            "research_status": "ready",
            "official_domain": "voorbeeld.nl",
            "evidence_candidates": evidence,
        })
        findings = result["selected_findings"]
        self.assertEqual(result["outreach_status"], "ready")
        self.assertEqual(len(findings), 6)
        self.assertNotIn("portfolio", {point["category"] for point in findings})
        self.assertEqual([point["score"] for point in findings], sorted(
            [point["score"] for point in findings], reverse=True,
        ))

    def test_ordinary_unverified_text_is_not_automatically_a_defect(self):
        result = select_one_reason({
            "research_status": "ready",
            "official_domain": "voorbeeld.nl",
            "evidence_candidates": [
                sourced("Wij bieden uitstekende kwaliteit met persoonlijke aandacht voor alle klanten.", "over"),
            ],
        })
        self.assertEqual(result["outreach_status"], "hold")


if __name__ == "__main__":
    unittest.main()
