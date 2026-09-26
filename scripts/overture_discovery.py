from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
import math
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests

from url_safety import is_public_http_url

PDOK_FREE_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
DEFAULT_RADIUS_KM = 8.0
DEFAULT_TIMEOUT_SECONDS = 15
MAX_RESULTS = 5000
MAX_PROBE_WORKERS = 8


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _flatten_text(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_flatten_text(item))
        return out
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_text(item))
        return out
    return [str(value)]


def _first_text(value) -> str | None:
    for item in _flatten_text(value):
        text = str(item).strip()
        if text:
            return text
    return None


EMAIL_RE = re.compile(r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63})(?![A-Z0-9._%+-])", re.I)


def _email_candidates(properties: dict) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for item in _flatten_text(properties.get("emails")):
        for match in EMAIL_RE.findall(str(item or "")):
            email = match.strip().lower().strip(".,;:()[]<>")
            if email and email not in seen:
                seen.add(email)
                found.append({"email": email, "source": "overture"})
    return found


def _website_hint(properties: dict) -> str | None:
    websites = properties.get("websites")
    if isinstance(websites, str):
        return websites.strip() if _valid_http_url(websites) else None
    if isinstance(websites, list):
        for item in websites:
            if isinstance(item, str) and _valid_http_url(item):
                return item.strip()
            if isinstance(item, dict):
                for key in ("url", "value", "website"):
                    value = item.get(key)
                    if isinstance(value, str) and _valid_http_url(value):
                        return value.strip()
    return None


def _primary_name(properties: dict) -> str | None:
    names = properties.get("names")
    if isinstance(names, dict):
        primary = names.get("primary")
        if isinstance(primary, str) and primary.strip():
            return primary.strip()
    return _first_text(names)


def _category_hint(properties: dict) -> str | None:
    for key in ("basic_category", "taxonomy", "categories"):
        value = properties.get(key)
        text = _first_text(value)
        if text:
            return text
    return None


def _parse_point_wkt(value: str) -> tuple[float, float]:
    match = re.fullmatch(
        r"\s*POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s*",
        str(value or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("PDOK centroide_ll is not a POINT WKT")
    return float(match.group(1)), float(match.group(2))


def resolve_region_center(
    region: str,
    *,
    session=requests,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    region = str(region or "").strip()
    if not region:
        raise ValueError("region is required")

    headers = {"User-Agent": "WebactueelLeadDiscovery/1.0 (+https://andrewbaeten.nl)"}
    fields = "id,weergavenaam,type,centroide_ll"

    for object_type in ("woonplaats", "gemeente"):
        response = session.get(
            PDOK_FREE_URL,
            params={
                "q": region,
                "fq": f"type:{object_type}",
                "fl": fields,
                "rows": 1,
                "wt": "json",
            },
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
        if not docs:
            continue
        doc = docs[0]
        lon, lat = _parse_point_wkt(doc.get("centroide_ll", ""))
        return {
            "query": region,
            "resolved_name": str(doc.get("weergavenaam") or region),
            "resolved_type": str(doc.get("type") or object_type),
            "pdok_id": str(doc.get("id") or ""),
            "lon": lon,
            "lat": lat,
            "source": "PDOK Locatieserver",
            "authentication": "none",
        }

    raise RuntimeError(f"PDOK could not resolve region: {region}")


def bbox_from_center(lon: float, lat: float, radius_km: float) -> tuple[float, float, float, float]:
    if not 0.5 <= radius_km <= 50:
        raise ValueError("radius_km must be between 0.5 and 50")
    lat_delta = radius_km / 110.574
    cos_lat = max(math.cos(math.radians(lat)), 0.2)
    lon_delta = radius_km / (111.320 * cos_lat)
    return (
        round(lon - lon_delta, 6),
        round(lat - lat_delta, 6),
        round(lon + lon_delta, 6),
        round(lat + lat_delta, 6),
    )


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [part.strip() for part in str(value or "").split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    west, south, east, north = [float(part) for part in parts]
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox coordinates are invalid")
    return west, south, east, north


def download_overture_places(
    bbox: tuple[float, float, float, float],
    output_path: Path,
    *,
    runner=subprocess.run,
) -> None:
    executable = shutil.which("overturemaps")
    if not executable:
        raise RuntimeError("overturemaps CLI is not installed; install requirements-discovery.txt")

    bbox_arg = ",".join(str(value) for value in bbox)
    result = runner(
        [
            executable,
            "download",
            "--bbox",
            bbox_arg,
            "-f",
            "geojsonseq",
            "--type",
            "place",
            "-o",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown overturemaps failure").strip()
        raise RuntimeError(f"overturemaps download failed: {detail[-1000:]}")
    if not output_path.exists():
        output_path.touch()


def _matches_keywords(properties: dict, keywords: list[str]) -> bool:
    """High-precision discovery filter.

    Match only the primary place name and Overture basic category. Broader taxonomy,
    alternate-category and brand fields are intentionally excluded because they can
    turn a narrow query (for example bakery) into unrelated chains that merely offer
    that product class. Discovery may return fewer candidates; the controller should
    refill with explicit adjacent keywords/regions instead of silently broadening.
    """
    if not keywords:
        return True
    selected = {
        "primary_name": _primary_name(properties),
        "basic_category": properties.get("basic_category"),
    }
    haystack = _normalize(" ".join(_flatten_text(selected)))
    return any(_normalize(keyword) in haystack for keyword in keywords if _normalize(keyword))


def read_candidates(
    path: Path,
    *,
    keywords: list[str],
    max_results: int,
    require_website: bool,
) -> list[dict]:
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be 1-{MAX_RESULTS}")

    candidates: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.lstrip("\x1e").strip()
            if not line:
                continue
            feature = json.loads(line)
            properties = feature.get("properties") or {}
            if not _matches_keywords(properties, keywords):
                continue

            status = _normalize(properties.get("operating_status"))
            if "closed" in status:
                continue

            website = _website_hint(properties)
            if require_website and not website:
                continue

            geometry = feature.get("geometry") or {}
            coords = geometry.get("coordinates") or []
            lon = coords[0] if len(coords) >= 2 else None
            lat = coords[1] if len(coords) >= 2 else None
            confidence = properties.get("confidence")
            try:
                confidence_value = float(confidence) if confidence is not None else None
            except (TypeError, ValueError):
                confidence_value = None

            candidates.append(
                {
                    "overture_id": str(feature.get("id") or properties.get("id") or "").strip(),
                    "name_hint": _primary_name(properties),
                    "category_hint": _category_hint(properties),
                    "website_hint": website,
                    "longitude": lon,
                    "latitude": lat,
                    "confidence": confidence_value,
                    "discovery_email_candidates": _email_candidates(properties),
                    "identity_status": "needs_leads_verification",
                }
            )

    candidates.sort(
        key=lambda item: (
            item["website_hint"] is None,
            -(item["confidence"] if item["confidence"] is not None else -1.0),
            _normalize(item["name_hint"]),
            item["overture_id"],
        )
    )

    deduplicated: list[dict] = []
    seen: set[tuple] = set()
    for item in candidates:
        overture_id = str(item.get("overture_id") or "").strip()
        key = (
            ("overture_id", overture_id)
            if overture_id
            else (
                "fallback",
                _normalize(item.get("name_hint")),
                _normalize(item.get("website_hint")),
                item.get("longitude"),
                item.get("latitude"),
            )
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
        if len(deduplicated) >= max_results:
            break
    return deduplicated


def probe_website(
    url: str,
    *,
    session=requests,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    if not is_public_http_url(url):
        return {
            "status": "blocked_non_public_url",
            "final_url": None,
            "http_status": None,
            "detail": "non_public_url",
        }
    try:
        response = session.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            stream=True,
            headers={"User-Agent": "WebactueelLeadDiscovery/1.0 (+https://andrewbaeten.nl)"},
        )
        try:
            status_code = int(response.status_code)
            final_url = str(response.url or "").strip()
        finally:
            response.close()
        if not is_public_http_url(final_url):
            return {
                "status": "blocked_non_public_url",
                "final_url": None,
                "http_status": status_code,
                "detail": "redirected_to_non_public_url",
            }
    except requests.RequestException as exc:
        return {
            "status": "unreachable",
            "final_url": None,
            "http_status": None,
            "detail": type(exc).__name__,
        }

    if 200 <= status_code < 400 and _valid_http_url(final_url):
        return {
            "status": "reachable_needs_leads_identity_verification",
            "final_url": final_url,
            "http_status": status_code,
            "detail": None,
        }
    return {
        "status": "unreachable",
        "final_url": None,
        "http_status": status_code,
        "detail": "non_success_http_status",
    }


def probe_candidates(
    candidates: list[dict],
    *,
    probe=probe_website,
    max_workers: int = MAX_PROBE_WORKERS,
) -> list[dict]:
    if not candidates:
        return []
    if not 1 <= max_workers <= MAX_PROBE_WORKERS:
        raise ValueError(f"max_workers must be 1-{MAX_PROBE_WORKERS}")

    def run(candidate: dict) -> dict:
        website = candidate.get("website_hint")
        if not website:
            return {
                "status": "not_available",
                "final_url": None,
                "http_status": None,
                "detail": None,
            }
        try:
            return probe(website)
        except Exception as exc:
            return {
                "status": "unreachable",
                "final_url": None,
                "http_status": None,
                "detail": f"probe_error:{type(exc).__name__}",
            }

    workers = min(max_workers, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(run, candidates))


def discover(
    *,
    region: str | None,
    bbox: str | None,
    radius_km: float,
    keywords: Iterable[str],
    max_results: int,
    require_website: bool,
    probe_websites: bool,
) -> dict:
    clean_keywords = [str(value).strip() for value in keywords if str(value).strip()]

    if bbox:
        resolved_region = None
        resolved_bbox = parse_bbox(bbox)
    else:
        if not region:
            raise ValueError("provide either --region or --bbox")
        resolved_region = resolve_region_center(region)
        resolved_bbox = bbox_from_center(
            resolved_region["lon"],
            resolved_region["lat"],
            radius_km,
        )

    with tempfile.TemporaryDirectory(prefix="webactueel-overture-") as tmpdir:
        data_path = Path(tmpdir) / "places.geojsonseq"
        download_overture_places(resolved_bbox, data_path)
        candidates = read_candidates(
            data_path,
            keywords=clean_keywords,
            max_results=max_results,
            require_website=require_website,
        )

    if probe_websites:
        probes = probe_candidates(candidates)
        for candidate, probe_result in zip(candidates, probes):
            candidate["website_probe"] = probe_result

    return {
        "schema_version": "webactueel-overture-discovery/1.1",
        "source": "Overture Maps Places",
        "source_access": "public cloud GeoParquet via official overturemaps client",
        "authentication": "none",
        "region_resolution": resolved_region,
        "bbox": list(resolved_bbox),
        "radius_km": None if bbox else radius_km,
        "keywords": clean_keywords,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "privacy_and_scope": {
            "email_candidates_emitted": any(
                item.get("discovery_email_candidates") for item in candidates
            ),
            "phones_emitted": False,
            "socials_emitted": False,
            "contact_basis_evaluated": False,
            "draftqueue_write": False,
            "email_send": False,
        },
        "handoff": {
            "owner": "leads",
            "required_next_step": "Open website_hint/final_url directly and verify company + domain identity before any qualification claim.",
            "discovery_data_is_not_prospect_claim_evidence": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--region")
    group.add_argument("--bbox", help="west,south,east,north")
    parser.add_argument("--radius-km", type=float, default=DEFAULT_RADIUS_KM)
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--require-website", action="store_true")
    parser.add_argument("--probe-websites", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = discover(
        region=args.region,
        bbox=args.bbox,
        radius_km=args.radius_km,
        keywords=args.keyword,
        max_results=args.max_results,
        require_website=args.require_website,
        probe_websites=args.probe_websites,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "OVERTURE_DISCOVERY=green "
        f"candidates={result['candidate_count']} authentication=none "
        "identity=needs_leads_verification email_candidates=bounded draftqueue_write=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
