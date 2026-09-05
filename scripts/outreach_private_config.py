#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from outreach_sender import build_sheets_service, get_values

# Changes to this outreach runtime trigger the main-branch validate-only workflow;
# live delivery still requires an explicit live request plus all runtime gates.
DEFAULT_CONFIG_SPREADSHEET_ID = "1iOBCaBq3MpsrYQiESAhjS1NMRQDXAWmkTh-U-63qzs4"
CONFIG_SHEET = "Config"
POSTAL_KEY = "OUTREACH_POSTAL_ADDRESS"


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def load_config(service, spreadsheet_id: str) -> dict[str, str]:
    values = get_values(service, spreadsheet_id, CONFIG_SHEET)
    if not values:
        raise RuntimeError("private outreach config is empty")
    header = [_text(value).casefold() for value in values[0][:2]]
    if header != ["key", "value"]:
        raise RuntimeError("private outreach config headers must be key,value")
    config: dict[str, str] = {}
    for row in values[1:]:
        key = _text(row[0]) if row else ""
        value = _text(row[1]) if len(row) > 1 else ""
        if key and value:
            config[key] = value
    return config


def _append_github_env(name: str, value: str) -> None:
    path = os.getenv("GITHUB_ENV", "").strip()
    if not path:
        raise RuntimeError("GITHUB_ENV is unavailable")
    delimiter = "WEB_ACTUEEL_PRIVATE_CONFIG_EOF"
    if delimiter in value:
        raise RuntimeError("private config value contains reserved delimiter")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def export_postal_address() -> int:
    spreadsheet_id = (
        os.getenv("OUTREACH_CONFIG_SPREADSHEET_ID", "").strip()
        or DEFAULT_CONFIG_SPREADSHEET_ID
    )
    service = build_sheets_service()
    config = load_config(service, spreadsheet_id)
    value = _text(config.get(POSTAL_KEY))
    if not value:
        raise RuntimeError("private outreach config is missing OUTREACH_POSTAL_ADDRESS")
    # Mask before exporting to later steps. The value is never supplied as a
    # repository variable, command-line argument, artifact or step summary.
    print(f"::add-mask::{value}")
    _append_github_env(POSTAL_KEY, value)
    print("PRIVATE_OUTREACH_CONFIG=green postal_address=present source=private_sheet")
    return 0


def main() -> int:
    try:
        return export_postal_address()
    except RuntimeError as exc:
        print(f"PRIVATE_OUTREACH_CONFIG=blocked detail={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
