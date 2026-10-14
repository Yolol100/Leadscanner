import unittest
from unittest.mock import patch

from new_leads import run
from overture_discovery import read_candidates
from target_scope import (
    is_allowed_requested_keyword,
    is_blocked_place,
    validate_requested_keywords,
)


class TargetScopeTests(unittest.TestCase):
    def test_broad_local_trade_profile_accepts_representative_normal_businesses(self):
        allowed = [
            "bouwbedrijf", "loodgieter", "elektricien", "dakdekker", "schilder",
            "hovenier", "schoonmaakbedrijf", "garage", "fietsenmaker", "kapsalon",
            "schoonheidssalon", "restaurant", "bakkerij", "verhuisbedrijf",
            "rijschool", "sportschool", "dierenarts", "tandarts", "fysiotherapie",
            "uitvaartverzorger", "muziekschool", "huiswerkbegeleiding", "hondentrainer",
            "feestlocatie", "tentenverhuur", "autoverhuur", "escape room", "klimhal",
        ]
        for keyword in allowed:
            with self.subTest(keyword=keyword):
                self.assertTrue(is_allowed_requested_keyword(keyword))
                self.assertEqual(validate_requested_keywords([keyword]), [keyword])

    def test_default_profile_covers_every_specific_trade_alias(self):
        from target_scope import REQUEST_CATEGORY_ALIASES, profile_category_terms, normalize
        expected = {normalize(alias)
                    for aliases in REQUEST_CATEGORY_ALIASES.values() for alias in aliases}
        actual = set(profile_category_terms())
        self.assertFalse(expected - actual)

    def test_default_profile_matches_missing_rare_trade(self):
        from overture_discovery import _matches_keywords
        fixtures = ("thatching_contractor", "building_cleaning_service",
                    "recreational_vehicle_repair_service", "holiday_accommodation")
        for category in fixtures:
            with self.subTest(category=category):
                props = {"names": {"primary": "Neutraal Lokaal Bedrijf"},
                         "basic_category": category}
                self.assertTrue(_matches_keywords(props, ["vakbedrijven"]))

    def test_profile_macro_is_allowed(self):
        for keyword in ("vakbedrijven", "lokale vakbedrijven", "lokale bedrijven"):
            with self.subTest(keyword=keyword):
                self.assertTrue(is_allowed_requested_keyword(keyword))

    def test_digital_and_consultancy_sectors_are_hard_blocked(self):
        blocked = [
            "marketingbureau", "webdesign", "seo bureau", "softwarebedrijf",
            "it consultancy", "ai bureau", "management consultancy", "boekhouder",
            "advocatenkantoor", "recruitment agency", "uitzendbureau",
            "verzekeringsadviseur", "hypotheekadviseur", "projectontwikkelaar",
            "dropshipping", "groothandel", "basisschool",
        ]
        for keyword in blocked:
            with self.subTest(keyword=keyword):
                with self.assertRaises(ValueError):
                    validate_requested_keywords([keyword])

    def test_unknown_sector_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_requested_keywords(["ruimtevaartadvies"])

    def test_place_blocklist_overrides_positive_name(self):
        self.assertTrue(is_blocked_place("Bouw Marketing Bureau", "marketing agency"))
        self.assertTrue(is_blocked_place("De Digitale Loodgieter", "web design agency"))
        self.assertFalse(is_blocked_place("Loodgietersbedrijf De Waterman", "plumber"))

    def test_run_rejects_blocked_target_before_registry_or_discovery(self):
        with patch("new_leads.load_suppressions") as registry, patch("new_leads.discover") as discovery:
            with self.assertRaises(ValueError):
                run("Leiden", ["marketingbureau"], 8, 10)
            registry.assert_not_called()
            discovery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
