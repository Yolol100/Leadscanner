#!/usr/bin/env python3
"""Fail closed before exporting prospect or provider data from public GitHub Actions."""
from __future__ import annotations

import argparse


def require_private_repository(value: str) -> None:
    """Only GitHub's exact boolean true is accepted; missing/unknown is unsafe."""
    if value != "true":
        raise ValueError("leadscanner_sensitive_workflow_requires_private_repository")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-private", required=True)
    args = parser.parse_args()
    try:
        require_private_repository(args.repository_private)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    print("LEADSCANNER_REPOSITORY_PRIVACY=green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
