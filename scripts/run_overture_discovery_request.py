from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from overture_discovery import discover

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,119}$")


def load_request(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("enabled") is not True:
        raise ValueError("request.enabled must be true")

    request_id = str(data.get("request_id") or "").strip()
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError("request_id must be 6-120 chars: letters, digits, dot, underscore or hyphen")

    region = str(data.get("region") or "").strip() or None
    bbox = str(data.get("bbox") or "").strip() or None
    if bool(region) == bool(bbox):
        raise ValueError("provide exactly one of region or bbox")

    radius_km = float(data.get("radius_km", 8))
    max_results = int(data.get("max_results", 20))
    if not 1 <= max_results <= 100:
        raise ValueError("max_results must be 1-100")

    keywords = data.get("keywords") or []
    if not isinstance(keywords, list) or len(keywords) > 12:
        raise ValueError("keywords must be an array with at most 12 values")
    clean_keywords = []
    for keyword in keywords:
        text = str(keyword).strip()
        if not text:
            continue
        if len(text) > 80:
            raise ValueError("keyword length must be <=80")
        clean_keywords.append(text)

    require_website = data.get("require_website", True)
    probe_websites = data.get("probe_websites", True)
    if not isinstance(require_website, bool) or not isinstance(probe_websites, bool):
        raise ValueError("require_website and probe_websites must be booleans")

    return {
        "request_id": request_id,
        "region": region,
        "bbox": bbox,
        "radius_km": radius_km,
        "keywords": clean_keywords,
        "max_results": max_results,
        "require_website": require_website,
        "probe_websites": probe_websites,
    }


def run(request_path: Path, output_path: Path) -> dict:
    request = load_request(request_path)
    result = discover(
        region=request["region"],
        bbox=request["bbox"],
        radius_km=request["radius_km"],
        keywords=request["keywords"],
        max_results=request["max_results"],
        require_website=request["require_website"],
        probe_websites=request["probe_websites"],
    )
    result["request_id"] = request["request_id"]
    result["runtime_transport"] = "temporary_git_branch"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = run(Path(args.request), Path(args.output))
    except Exception as exc:
        print(f"OVERTURE_RUNTIME_DISCOVERY=blocked detail={exc}")
        return 2
    print(
        "OVERTURE_RUNTIME_DISCOVERY=green "
        f"request_id={result['request_id']} candidates={result['candidate_count']} "
        "authentication=none draftqueue_write=false email_send=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
