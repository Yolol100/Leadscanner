import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import outreach_copy_v17_3 as c


class V173PolicyTests(unittest.TestCase):
    def good(self, **kwargs):
        args = dict(
            company="Demo Dak",
            language="nl",
            subject="Offerte aanvragen Demo",
            observation='Ik zag op jullie site de route "Offerte aanvragen" direct naast dakrenovatie',
            friction="Dat kan onnodig heen-en-weer opleveren voordat de basisinformatie voor een eerste aanvraag compleet is",
            example_label="mini-flow",
        )
        args.update(kwargs)
        return c.build_curiosity_first_copy(**args)

    def test_default_does_not_claim_artifact_exists(self):
        draft = self.good()
        self.assertEqual(c.POLICY_VERSION, "17.3.0")
        self.assertIn("Ik kan één korte flow maken", draft.body)
        self.assertNotIn("Ik heb één korte flow", draft.body)
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body), [])

    def test_proven_artifact_can_be_claimed(self):
        draft = self.good(artifact_ready=True)
        self.assertIn("Ik heb één korte flow uitgewerkt", draft.body)
        self.assertEqual(c.initial_copy_errors(draft.subject, draft.body, artifact_ready=True), [])

    def test_unproven_artifact_claim_is_blocked(self):
        draft = self.good(artifact_ready=True)
        self.assertTrue(any("artifact readback proof" in error for error in c.initial_copy_errors(draft.subject, draft.body)))

    def test_ads_do_not_prove_budget(self):
        with self.assertRaisesRegex(ValueError, "unsupported inferred claim"):
            self.good(friction="Omdat jullie Google Ads draaien is er duidelijk budget voor deze oplossing")

    def test_social_silence_does_not_prove_closed_business(self):
        with self.assertRaisesRegex(ValueError, "unsupported inferred claim"):
            self.good(friction="Jullie bedrijf lijkt gesloten omdat social al maanden stil is")

    def test_llms_txt_is_not_visibility_proof(self):
        with self.assertRaisesRegex(ValueError, "unsupported inferred claim"):
            self.good(friction="Omdat llms.txt ontbreekt kan AI jullie bedrijf niet aanbevelen in Google Search")


if __name__ == "__main__":
    unittest.main()
