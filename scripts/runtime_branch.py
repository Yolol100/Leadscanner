from __future__ import annotations

import argparse
import re

PREFIX = "runtime/myhost-draft/"
LEAD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def parse_runtime_branch(branch: str) -> str:
    value = str(branch or "").strip()
    if not value.startswith(PREFIX):
        raise ValueError(f"runtime branch must start with {PREFIX}")
    lead_id = value[len(PREFIX):]
    if not LEAD_ID_RE.fullmatch(lead_id):
        raise ValueError("runtime lead_id must be 1-80 chars: letters, digits, dot, underscore or hyphen")
    return lead_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    try:
        print(parse_runtime_branch(args.branch))
    except ValueError as exc:
        print(f"RUNTIME_BRANCH=blocked detail={exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
