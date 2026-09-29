from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_verified_draft_input import build_contacts
from prepare_growth_batch import stable_lead_id


class BuildVerifiedDraftInputTests(unittest.TestCase):
    def make_source(self, root: Path, rows: list[dict]):
        root.mkdir(parents=True, exist_ok=True)
        ready = []
        contacts = []
        for row in rows:
            email = row["email"]
            domain = row["domain"]
            website = row["website"]
            ready.append(
                {
                    "company": row["company"],
                    "official_domain": domain,
                    "email": email,
                }
            )
            contacts.append(
                {
                    "name_hint": row["company"],
                    "website_hint": website,
                    "official_domain_hint": domain,
                    "public_business_emails": [email],
                    "email_source_urls": [website + "/contact"],
                    "email_source_types": ["official_site"],
                    "email_source_refs": [website + "/contact"],
                    "verified_observation": row["observation"],
                    "verified_observation_source_url": website,
                    "verified_observation_source_type": "official_site",
                    "language": "nl",
                    "language_source": "html_lang",
                    "excluded_competitor": False,
                    "contact_basis_status": "review_required",
                    "contact_basis_hint": "public_email_review_required",
                }
            )
        (root / "verification-ready.json").write_text(
            json.dumps({"ready_for_copy": ready}), encoding="utf-8"
        )
        (root / "public-contacts.json").write_text(
            json.dumps({"candidates": contacts}), encoding="utf-8"
        )

    def test_existing_growth_ids_are_excluded_before_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            rows = [
                {
                    "company": "A BV",
                    "domain": "a.nl",
                    "website": "https://a.nl",
                    "email": "info@a.nl",
                    "observation": "Dienstverlening voor bedrijven",
                },
                {
                    "company": "B BV",
                    "domain": "b.nl",
                    "website": "https://b.nl",
                    "email": "info@b.nl",
                    "observation": "Specialist in Nederland",
                },
            ]
            self.make_source(root, rows)
            inventory = {
                "growth_lead_ids": [stable_lead_id("info@a.nl", "https://a.nl")]
            }
            result = build_contacts([root], inventory, 1)
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["inventory_excluded_count"], 1)
            self.assertEqual(result["candidates"][0]["name_hint"], "B BV")
            self.assertFalse(result["safety"]["automatic_send"])

    def test_revalidates_old_verified_email_and_uses_next_currently_valid_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            root.mkdir(parents=True, exist_ok=True)
            (root / "verification-ready.json").write_text(
                json.dumps(
                    {
                        "ready_for_copy": [
                            {
                                "company": "A BV",
                                "official_domain": "a.nl",
                                "email": "press@a.nl",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "public-contacts.json").write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "name_hint": "A BV",
                                "website_hint": "https://a.nl",
                                "official_domain_hint": "a.nl",
                                "public_business_emails": ["press@a.nl", "info@a.nl"],
                                "email_source_urls": [
                                    "https://a.nl/contact",
                                    "https://a.nl/contact",
                                ],
                                "email_source_types": ["official_site", "official_site"],
                                "email_source_refs": [
                                    "https://a.nl/contact",
                                    "https://a.nl/contact",
                                ],
                                "verified_observation": "Dienstverlening voor bedrijven",
                                "verified_observation_source_url": "https://a.nl",
                                "verified_observation_source_type": "official_site",
                                "language": "nl",
                                "language_source": "html_lang",
                                "excluded_competitor": False,
                                "contact_basis_status": "review_required",
                                "contact_basis_hint": "public_email_review_required",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = build_contacts([root], {"growth_lead_ids": []}, 1)
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["candidates"][0]["public_business_emails"], ["info@a.nl"])

    def test_fails_closed_when_not_enough_new_verified_prospects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            self.make_source(
                root,
                [
                    {
                        "company": "A BV",
                        "domain": "a.nl",
                        "website": "https://a.nl",
                        "email": "info@a.nl",
                        "observation": "Dienstverlening voor bedrijven",
                    }
                ],
            )
            with self.assertRaises(RuntimeError):
                build_contacts([root], {"growth_lead_ids": []}, 2)


if __name__ == "__main__":
    unittest.main()
