from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

MAX_VERIFY = 100


def normalize_domain(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text if "://" in text else f"https://{text}"
    try:
        host = (urlparse(candidate).hostname or "").casefold().rstrip(".")
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def identity_keys(item: dict) -> list[str]:
    keys: list[str] = []
    domain = normalize_domain(item.get("website_hint"))
    if domain:
        keys.append("domain:" + domain)
    for field, prefix in (
        ("google_maps_place_id", "place:"),
        ("google_maps_cid", "cid:"),
        ("overture_id", "overture:"),
    ):
        value = str(item.get(field) or "").strip()
        if value:
            keys.append(prefix + value)
    return keys


def select_candidates(phase2: dict, hybrid: dict, *, offset: int, limit: int) -> dict:
    if not 0 <= offset:
        raise ValueError("offset must be >= 0")
    if not 1 <= limit <= MAX_VERIFY:
        raise ValueError(f"limit must be 1-{MAX_VERIFY}")

    phase2_candidates = phase2.get("candidates") or []
    hybrid_candidates = hybrid.get("candidates") or []
    if not isinstance(phase2_candidates, list) or not isinstance(hybrid_candidates, list):
        raise ValueError("candidate collections must be lists")

    hybrid_by_key: dict[str, dict] = {}
    for item in hybrid_candidates:
        if not isinstance(item, dict):
            continue
        for key in identity_keys(item):
            hybrid_by_key.setdefault(key, item)

    selected: list[dict] = []
    unmatched = 0
    for base in phase2_candidates[offset : offset + limit]:
        if not isinstance(base, dict):
            continue
        match = None
        for key in identity_keys(base):
            match = hybrid_by_key.get(key)
            if match:
                break
        if match:
            merged = dict(match)
            merged.update({k: v for k, v in base.items() if v not in (None, "", [])})
            selected.append(merged)
        else:
            unmatched += 1
            selected.append(dict(base))

    return {
        "schema_version": "webactueel-verification-input/1.0",
        "source_phase2_candidate_count": len(phase2_candidates),
        "offset": offset,
        "limit": limit,
        "selected_count": len(selected),
        "unmatched_hybrid_count": unmatched,
        "candidates": selected,
        "safety": {
            "verification_only": True,
            "copy_created": False,
            "draft_created": False,
            "email_send": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase2", required=True)
    parser.add_argument("--hybrid", required=True)
    parser.add_argument("--offset", type=int, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    phase2 = json.loads(Path(args.phase2).read_text(encoding="utf-8"))
    hybrid = json.loads(Path(args.hybrid).read_text(encoding="utf-8"))
    result = select_candidates(phase2, hybrid, offset=args.offset, limit=args.limit)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "VERIFY_INPUT=green "
        f"selected={result['selected_count']} offset={result['offset']} "
        f"unmatched_hybrid={result['unmatched_hybrid_count']} "
        "copy=false draft=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
