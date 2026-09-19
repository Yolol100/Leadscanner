from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
from google.maps import places_v1

MAX_RESULTS_PER_QUERY = 20
DEFAULT_TIMEOUT_SECONDS = 12


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_places_client():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        info = json.loads(raw)
        return places_v1.PlacesClient.from_service_account_info(info)
    return places_v1.PlacesClient()


def search_place_ids(
    client,
    query: str,
    *,
    max_results: int = 20,
    region_code: str = "NL",
) -> list[str]:
    if not 1 <= max_results <= MAX_RESULTS_PER_QUERY:
        raise ValueError(f"max_results must be 1-{MAX_RESULTS_PER_QUERY}")

    request = places_v1.SearchTextRequest(
        text_query=query,
        region_code=region_code,
    )
    response = client.search_text(
        request=request,
        metadata=[("x-goog-fieldmask", "places.id")],
        timeout=30,
    )

    found: list[str] = []
    for place in response.places:
        place_id = str(place.id or "").strip()
        if place_id and place_id not in found:
            found.append(place_id)
            if len(found) >= max_results:
                break
    return found


def resolve_website_uri(client, place_id: str) -> str | None:
    place = client.get_place(
        name=f"places/{place_id}",
        metadata=[("x-goog-fieldmask", "id,websiteUri")],
        timeout=30,
    )
    website_uri = str(getattr(place, "website_uri", "") or "").strip()
    return website_uri if _valid_http_url(website_uri) else None


def verify_official_site(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            stream=True,
            headers={"User-Agent": "WebactueelLeadDiscovery/1.0"},
        )
        try:
            final_url = str(response.url or "").strip()
            status_code = int(response.status_code)
        finally:
            response.close()
    except requests.RequestException as exc:
        return {
            "status": "unreachable",
            "official_site_url": None,
            "http_status": None,
            "detail": type(exc).__name__,
        }

    if 200 <= status_code < 400 and _valid_http_url(final_url):
        return {
            "status": "http_reachable_needs_leads_identity_verification",
            "official_site_url": final_url,
            "http_status": status_code,
            "detail": None,
        }

    return {
        "status": "unreachable",
        "official_site_url": None,
        "http_status": status_code,
        "detail": "non_success_http_status",
    }


def discover(
    queries: Iterable[str],
    *,
    max_results_per_query: int = 20,
    region_code: str = "NL",
    client=None,
) -> dict:
    clean_queries = [str(q).strip() for q in queries if str(q).strip()]
    if not clean_queries:
        raise ValueError("at least one non-empty query is required")
    if not 1 <= max_results_per_query <= MAX_RESULTS_PER_QUERY:
        raise ValueError(f"max_results_per_query must be 1-{MAX_RESULTS_PER_QUERY}")

    client = client or build_places_client()

    ordered_ids: list[str] = []
    seen: set[str] = set()
    query_counts: dict[str, int] = {}

    for query in clean_queries:
        ids = search_place_ids(
            client,
            query,
            max_results=max_results_per_query,
            region_code=region_code,
        )
        query_counts[query] = len(ids)
        for place_id in ids:
            if place_id not in seen:
                seen.add(place_id)
                ordered_ids.append(place_id)

    candidates = []
    for place_id in ordered_ids:
        website_uri = resolve_website_uri(client, place_id)
        if not website_uri:
            candidates.append(
                {
                    "place_id": place_id,
                    "discovery_status": "no_public_website_from_places",
                    "official_site_url": None,
                    "http_status": None,
                    "identity_status": "unverified",
                }
            )
            continue

        verified = verify_official_site(website_uri)
        candidates.append(
            {
                "place_id": place_id,
                "discovery_status": verified["status"],
                "official_site_url": verified["official_site_url"],
                "http_status": verified["http_status"],
                "identity_status": "needs_leads_verification",
            }
        )

    return {
        "schema_version": "webactueel-google-places-discovery/1.0",
        "source": "Google Places API (New)",
        "region_code": region_code,
        "queries": clean_queries,
        "query_counts": query_counts,
        "unique_place_ids": len(ordered_ids),
        "candidates": candidates,
        "maps_storage_policy": {
            "persisted_google_maps_fields": ["place_id"],
            "discarded_after_immediate_use": ["websiteUri"],
            "display_name_address_reviews_requested": False,
        },
        "handoff": {
            "owner": "leads",
            "required_next_step": "Open the returned official_site_url directly and verify company/domain identity before qualification.",
            "identity_is_not_verified_by_this_adapter": True,
            "draftqueue_write": False,
            "email_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--queries-file")
    parser.add_argument("--max-results-per-query", type=int, default=20)
    parser.add_argument("--region-code", default="NL")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    queries = list(args.query)
    if args.queries_file:
        queries.extend(
            line.strip()
            for line in Path(args.queries_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    result = discover(
        queries,
        max_results_per_query=args.max_results_per_query,
        region_code=args.region_code,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "GOOGLE_PLACES_DISCOVERY=green "
        f"queries={len(result['queries'])} unique_place_ids={result['unique_place_ids']} "
        "identity=needs_leads_verification draftqueue_write=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
