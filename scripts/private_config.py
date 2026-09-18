from __future__ import annotations

import os

from sheets import build_service, get_values

DEFAULT_CONFIG_SPREADSHEET_ID = "1iOBCaBq3MpsrYQiESAhjS1NMRQDXAWmkTh-U-63qzs4"
CONFIG_SHEET = "Config"


def load_private_postal_address() -> str:
    spreadsheet_id = os.getenv("OUTREACH_CONFIG_SPREADSHEET_ID", "").strip() or DEFAULT_CONFIG_SPREADSHEET_ID
    values = get_values(build_service(), spreadsheet_id, CONFIG_SHEET)
    if not values or [str(x).strip().casefold() for x in values[0][:2]] != ["key", "value"]:
        raise RuntimeError("Private Config sheet must start with key,value")
    config = {}
    for row in values[1:]:
        if not row:
            continue
        key = str(row[0]).strip()
        value = " ".join(str(row[1]).split()).strip() if len(row) > 1 else ""
        if key and value:
            config[key] = value
    address = config.get("OUTREACH_POSTAL_ADDRESS", "").strip()
    if not address:
        raise RuntimeError("OUTREACH_POSTAL_ADDRESS is missing from private config")
    return address
