"""Validate read-only GitHub discovery requests; never interpolate into a shell."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys


def resolve_request(event_name: str, event_payload: dict, inputs: dict) -> tuple:
    if event_name == "push":
        message = str((event_payload.get("head_commit") or {}).get("message") or "")
        first_line = message.splitlines()[0].strip() if message else ""
        match = re.fullmatch(
            r"LEADS_DISCOVERY_ONLY:\s*([A-Za-zÀ-ÿ '\-]{2,100})\|([A-Za-zÀ-ÿ ,\-]{2,150})\|([1-9][0-9]?)",
            first_line,
        )
        if not match:
            raise ValueError("invalid_push_request")
        region, keywords, limit = match.groups()
        radius = "25"
    elif event_name == "workflow_dispatch":
        if inputs.get("execution_mode") != "discover":
            raise ValueError("invalid_dispatch_mode")
        region = str(inputs.get("region") or "")
        keywords = str(inputs.get("keywords") or "")
        limit = str(inputs.get("limit") or "")
        radius = str(inputs.get("radius_km") or "")
    else:
        raise ValueError("untrusted_event")
    region, keywords = region.strip(), keywords.strip()
    words = [v.strip() for v in keywords.split(",") if v.strip()]
    if not (2 <= len(region) <= 100 and 1 <= len(words) <= 8
            and all(2 <= len(w) <= 64 for w in words)):
        raise ValueError("invalid_region_or_keywords")
    try:
        limit_int = int(limit)
        radius_float = float(radius)
    except ValueError:
        raise ValueError("invalid_limits") from None
    if not (1 <= limit_int <= 100 and 0.5 <= radius_float <= 30):
        raise ValueError("limits_out_of_bounds")
    return region, ",".join(words), str(limit_int), str(radius_float)


def main() -> int:
    try:
        event_name = os.environ.get("GITHUB_EVENT_NAME") or ""
        event_json = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        request = resolve_request(event_name, event_json, {
            "execution_mode": os.environ.get("EXECUTION_MODE", ""),
            "region": os.environ.get("REGION", ""),
            "keywords": os.environ.get("KEYWORDS", ""),
            "limit": os.environ.get("LIMIT", ""),
            "radius_km": os.environ.get("RADIUS", ""),
        })
        subprocess.run([sys.executable, "scripts/new_leads.py",
                        "--region", request[0], "--keywords", request[1],
                        "--limit", request[2], "--radius-km", request[3],
                        "--summary-only", "--private-handoff"], check=True)
        return 0
    except Exception:
        print("FRESH_LEADS_REQUEST=red details_suppressed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
