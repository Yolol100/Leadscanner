import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from google_places_discovery import (
    build_places_client,
    discover,
    search_place_ids,
    verify_official_site,
)


class FakePlacesClient:
    def __init__(self):
        self.search_calls = []
        self.detail_calls = []

    def search_text(self, request, metadata, timeout):
        self.search_calls.append((request, metadata, timeout))
        query = request.text_query
        if query == "bakker Rotterdam":
            places = [SimpleNamespace(id="p1"), SimpleNamespace(id="p2")]
        elif query == "bakker Schiedam":
            places = [SimpleNamespace(id="p2"), SimpleNamespace(id="p3")]
        else:
            places = []
        return SimpleNamespace(places=places, next_page_token="")

    def get_place(self, name, metadata, timeout):
        self.detail_calls.append((name, metadata, timeout))
        place_id = name.split("/", 1)[1]
        mapping = {
            "p1": "https://one.example/",
            "p2": "https://two.example/",
            "p3": "",
        }
        return SimpleNamespace(website_uri=mapping[place_id])


class DiscoveryTests(unittest.TestCase):
    def test_ids_only_search_mask_and_dedup(self):
        client = FakePlacesClient()
        ids = search_place_ids(client, "bakker Rotterdam", max_results=20, region_code="NL")
        self.assertEqual(ids, ["p1", "p2"])
        _, metadata, _ = client.search_calls[0]
        self.assertIn(("x-goog-fieldmask", "places.id,nextPageToken"), metadata)

    def test_rejects_more_than_60_results_per_query(self):
        client = FakePlacesClient()
        with self.assertRaises(ValueError):
            search_place_ids(client, "bakker Rotterdam", max_results=61)

    @patch("google_places_discovery.verify_official_site")
    def test_discover_persists_only_place_id_from_maps(self, verify):
        verify.side_effect = [
            {
                "status": "http_reachable_needs_leads_identity_verification",
                "official_site_url": "https://one.example/",
                "http_status": 200,
                "detail": None,
            },
            {
                "status": "http_reachable_needs_leads_identity_verification",
                "official_site_url": "https://two.example/",
                "http_status": 200,
                "detail": None,
            },
        ]
        result = discover(
            ["bakker Rotterdam", "bakker Schiedam"],
            max_results_per_query=20,
            region_code="NL",
            client=FakePlacesClient(),
        )
        self.assertEqual(result["unique_place_ids"], 3)
        self.assertEqual([x["place_id"] for x in result["candidates"]], ["p1", "p2", "p3"])
        self.assertEqual(result["maps_storage_policy"]["persisted_google_maps_fields"], ["place_id"])
        self.assertTrue(result["maps_storage_policy"]["display_name_address_reviews_requested"] is False)
        self.assertTrue(result["handoff"]["identity_is_not_verified_by_this_adapter"])
        self.assertFalse(result["handoff"]["draftqueue_write"])
        self.assertFalse(result["handoff"]["email_send"])

    @patch("google_places_discovery.requests.get")
    def test_verify_official_site_uses_direct_http_readback(self, get):
        response = Mock()
        response.url = "https://final.example/"
        response.status_code = 200
        response.close = Mock()
        get.return_value = response
        result = verify_official_site("https://start.example/")
        self.assertEqual(result["status"], "http_reachable_needs_leads_identity_verification")
        self.assertEqual(result["official_site_url"], "https://final.example/")
        self.assertEqual(result["http_status"], 200)
        response.close.assert_called_once()

    @patch("google_places_discovery.places_v1.PlacesClient.from_service_account_info")
    def test_existing_service_account_json_can_supply_adc_client(self, factory):
        factory.return_value = object()
        with patch.dict(
            os.environ,
            {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account", "project_id": "test"})},
            clear=False,
        ):
            client = build_places_client()
        self.assertIs(client, factory.return_value)
        factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
