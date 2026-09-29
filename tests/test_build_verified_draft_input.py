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

    def test_existing_growth_email_excludes_cross_batch_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            rows = [
                {
                    "company": "VanHaren",
                    "domain": "stores.vanharen.nl",
                    "website": "https://stores.vanharen.nl/rotterdam",
                    "email": "klantenservice@vanharen.nl",
                    "observation": "Winkel Rotterdam",
                },
                {
                    "company": "Andere Winkel",
                    "domain": "anderewinkel.nl",
                    "website": "https://anderewinkel.nl",
                    "email": "info@anderewinkel.nl",
                    "observation": "Schoenen en accessoires",
                },
            ]
            self.make_source(root, rows)
            result = build_contacts(
                [root],
                {
                    "growth_lead_ids": [],
                    "growth_emails": ["klantenservice@vanharen.nl"],
                },
                1,
            )
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["inventory_excluded_count"], 1)
            self.assertEqual(result["candidates"][0]["name_hint"], "Andere Winkel")
            self.assertTrue(result["safety"]["existing_growth_emails_excluded"])

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

    def test_reorders_old_verified_emails_by_current_business_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            root.mkdir(parents=True, exist_ok=True)
            (root / "verification-ready.json").write_text(
                json.dumps(
                    {
                        "ready_for_copy": [
                            {
                                "company": "Albert Heijn Bunnik",
                                "official_domain": "hansgeveling.nl",
                                "email": "mt.8507@ah.nl",
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
                                "name_hint": "Albert Heijn Bunnik",
                                "website_hint": "https://hansgeveling.nl/winkels/bunnik/",
                                "official_domain_hint": "hansgeveling.nl",
                                "public_business_emails": [
                                    "mt.8507@ah.nl",
                                    "info@hansgeveling.nl",
                                ],
                                "email_source_urls": [
                                    "https://hansgeveling.nl/winkels/bunnik/",
                                    "https://hansgeveling.nl/contact/",
                                ],
                                "email_source_types": ["official_site", "official_site"],
                                "email_source_refs": [
                                    "https://hansgeveling.nl/winkels/bunnik/",
                                    "https://hansgeveling.nl/contact/",
                                ],
                                "verified_observation": "Albert Heijn Bunnik",
                                "verified_observation_source_url": "https://hansgeveling.nl/winkels/bunnik/",
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
            result = build_contacts([root], {"growth_lead_ids": [], "growth_emails": []}, 1)
            self.assertEqual(
                result["candidates"][0]["public_business_emails"],
                ["info@hansgeveling.nl"],
            )

    def test_primary_site_wins_over_secondary_company_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            root.mkdir(parents=True, exist_ok=True)
            ready = [
                {"company": "New York Pizza", "official_domain": "nypjobs.nl", "email": "info@nypjobs.nl"},
                {"company": "New York Pizza", "official_domain": "newyorkpizza.nl", "email": "service@newyorkpizza.nl"},
                {"company": "VanHaren", "official_domain": "stores.vanharen.nl", "email": "klantenservice@vanharen.nl"},
                {"company": "VanHaren", "official_domain": "vanharen.nl", "email": "klantenservice@vanharen.nl"},
            ]
            contacts = [
                {
                    "name_hint": "New York Pizza",
                    "website_hint": "https://nypjobs.nl/",
                    "official_domain_hint": "nypjobs.nl",
                    "public_business_emails": ["info@nypjobs.nl"],
                    "email_source_urls": ["https://nypjobs.nl/"],
                    "email_source_types": ["official_site"],
                    "email_source_refs": ["https://nypjobs.nl/"],
                    "verified_observation": "Werken bij New York Pizza",
                    "verified_observation_source_url": "https://nypjobs.nl/",
                    "verified_observation_source_type": "official_site",
                    "language": "nl",
                    "language_source": "html_lang",
                    "excluded_competitor": False,
                    "contact_basis_status": "review_required",
                },
                {
                    "name_hint": "New York Pizza",
                    "website_hint": "https://newyorkpizza.nl/",
                    "official_domain_hint": "newyorkpizza.nl",
                    "public_business_emails": ["service@newyorkpizza.nl"],
                    "email_source_urls": ["https://newyorkpizza.nl/contact"],
                    "email_source_types": ["official_site"],
                    "email_source_refs": ["https://newyorkpizza.nl/contact"],
                    "verified_observation": "Pizza bestellen",
                    "verified_observation_source_url": "https://newyorkpizza.nl/",
                    "verified_observation_source_type": "official_site",
                    "language": "nl",
                    "language_source": "html_lang",
                    "excluded_competitor": False,
                    "contact_basis_status": "review_required",
                },
                {
                    "name_hint": "VanHaren",
                    "website_hint": "https://stores.vanharen.nl/rotterdam",
                    "official_domain_hint": "stores.vanharen.nl",
                    "public_business_emails": ["klantenservice@vanharen.nl"],
                    "email_source_urls": ["https://stores.vanharen.nl/rotterdam"],
                    "email_source_types": ["official_site"],
                    "email_source_refs": ["https://stores.vanharen.nl/rotterdam"],
                    "verified_observation": "Winkel Rotterdam",
                    "verified_observation_source_url": "https://stores.vanharen.nl/rotterdam",
                    "verified_observation_source_type": "official_site",
                    "language": "nl",
                    "language_source": "html_lang",
                    "excluded_competitor": False,
                    "contact_basis_status": "review_required",
                },
                {
                    "name_hint": "VanHaren",
                    "website_hint": "https://vanharen.nl/",
                    "official_domain_hint": "vanharen.nl",
                    "public_business_emails": ["klantenservice@vanharen.nl"],
                    "email_source_urls": ["https://vanharen.nl/contact"],
                    "email_source_types": ["official_site"],
                    "email_source_refs": ["https://vanharen.nl/contact"],
                    "verified_observation": "Schoenen en accessoires",
                    "verified_observation_source_url": "https://vanharen.nl/",
                    "verified_observation_source_type": "official_site",
                    "language": "nl",
                    "language_source": "html_lang",
                    "excluded_competitor": False,
                    "contact_basis_status": "review_required",
                },
            ]
            (root / "verification-ready.json").write_text(json.dumps({"ready_for_copy": ready}), encoding="utf-8")
            (root / "public-contacts.json").write_text(json.dumps({"candidates": contacts}), encoding="utf-8")
            result = build_contacts([root], {"growth_lead_ids": [], "growth_emails": []}, 2)
            self.assertEqual(
                [candidate["official_domain_hint"] for candidate in result["candidates"]],
                ["newyorkpizza.nl", "vanharen.nl"],
            )

    def test_same_brand_distinct_locations_remain_selectable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            rows = [
                {
                    "company": "Anytime Fitness",
                    "domain": "afeindhoven.nl",
                    "website": "https://afeindhoven.nl/",
                    "email": "eindhoven@anytimefitness.nl",
                    "observation": "Fitness Eindhoven",
                },
                {
                    "company": "Anytime Fitness",
                    "domain": "afrotterdamzevenkamp.nl",
                    "website": "https://afrotterdamzevenkamp.nl/",
                    "email": "rotterdam-zevenkamp@anytimefitness.nl",
                    "observation": "Fitness Rotterdam",
                },
            ]
            self.make_source(root, rows)
            result = build_contacts([root], {"growth_lead_ids": [], "growth_emails": []}, 2)
            self.assertEqual(result["selected_count"], 2)
            self.assertEqual(
                [candidate["official_domain_hint"] for candidate in result["candidates"]],
                ["afeindhoven.nl", "afrotterdamzevenkamp.nl"],
            )

    def test_explicit_registry_company_domain_exclusions_are_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            rows = [
                {
                    "company": "Jumbo",
                    "domain": "jumbo.com",
                    "website": "https://jumbo.com/",
                    "email": "klantenservice@jumbo.com",
                    "observation": "Boodschappen en winkels",
                },
                {
                    "company": "Andere Supermarkt",
                    "domain": "andere-supermarkt.nl",
                    "website": "https://andere-supermarkt.nl/",
                    "email": "info@andere-supermarkt.nl",
                    "observation": "Boodschappen en winkels",
                },
            ]
            self.make_source(root, rows)
            result = build_contacts(
                [root],
                {"growth_lead_ids": [], "growth_emails": []},
                1,
                excluded_companies={"Jumbo"},
                excluded_domains={"jumbo.com"},
            )
            self.assertEqual(result["selected_count"], 1)
            self.assertEqual(result["request_excluded_count"], 1)
            self.assertEqual(result["candidates"][0]["name_hint"], "Andere Supermarkt")
            self.assertTrue(result["safety"]["request_company_domain_exclusions_applied"])

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


    def test_fails_closed_when_mailbox_inventory_reports_duplicates(self):
        inventory = {
            "growth_lead_ids": ["growth-0123456789abcdefabcd"],
            "growth_emails": ["info@example.nl"],
            "duplicate_growth_lead_ids": ["growth-0123456789abcdefabcd"],
            "duplicate_growth_emails": ["info@example.nl"],
        }
        with self.assertRaisesRegex(RuntimeError, "duplicate drafts"):
            build_contacts([], inventory, 1)

if __name__ == "__main__":
    unittest.main()
