#!/usr/bin/env python3
"""One-time privacy remediation for public GitHub Actions artifacts.

The list and deletion phases are bounded; no recipient, artifact name, or
message content is printed. Existing aggregate-only research/sync artifacts
are left intact. This does not delete historical workflow logs.
"""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "Yolol100/Leadscanner"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts"
MAX_PAGES = 100
MAX_ARTIFACTS = 10_000
# Aggregate-only reports were explicitly designed not to contain recipient data.
SAFE_AGGREGATE = (
    re.compile(r"^site-research-\d+-\d+$", re.I),
    re.compile(r"^instantly-sync-\d+$", re.I),
)
# Unknown old artifacts with an outreach-related name are conservatively removed.
SENSITIVE_HINTS = (
    "lead", "prospect", "mail", "draft", "preview", "review", "contact",
    "outreach", "smtp", "campaign", "growth", "command", "instantly-control",
)


def should_delete(name: str) -> bool:
    if not isinstance(name, str) or not name.strip():
        # Unidentifiable archives are not assumed safe on a public repository.
        return True
    text = name.casefold()
    if any(pattern.fullmatch(text) for pattern in SAFE_AGGREGATE):
        return False
    return any(fragment in text for fragment in SENSITIVE_HINTS)


def _api(method: str, url: str, token: str):
    request = Request(
        url,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Leadscanner-artifact-privacy-cleanup",
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            if method == "DELETE":
                if response.status != 204:
                    raise RuntimeError("artifact_cleanup_delete_not_confirmed")
                return None
            if response.status != 200:
                raise RuntimeError("artifact_cleanup_get_not_confirmed")
            return json.loads(response.read(5_000_000).decode("utf-8"))
    except (HTTPError, URLError) as exc:
        # Do not print URLs, token values, or remote response bodies.
        raise RuntimeError("artifact_cleanup_github_api_failed") from None


def list_all(token: str) -> list[dict]:
    items = []
    reported_total = None
    for page in range(1, MAX_PAGES + 1):
        response = _api("GET", f"{API_ROOT}?per_page=100&page={page}", token)
        if not isinstance(response, dict):
            raise RuntimeError("artifact_cleanup_unexpected_listing")
        total = response.get("total_count")
        batch = response.get("artifacts")
        if type(total) is not int or not isinstance(batch, list):
            raise RuntimeError("artifact_cleanup_invalid_listing")
        if reported_total is None:
            reported_total = total
            if total > MAX_ARTIFACTS:
                raise RuntimeError("artifact_cleanup_too_many_artifacts")
        if total != reported_total:
            raise RuntimeError("artifact_cleanup_listing_changed")
        if len(items) + len(batch) > MAX_ARTIFACTS:
            raise RuntimeError("artifact_cleanup_too_many_artifacts")
        items.extend(batch)
        if len(items) >= total:
            if len(items) != total:
                raise RuntimeError("artifact_cleanup_listing_count_drift")
            break
        if not batch:
            raise RuntimeError("artifact_cleanup_listing_incomplete")
    else:
        raise RuntimeError("artifact_cleanup_pagination_limit")
    ids = [item.get("id") for item in items]
    if any(type(i) is not int or i <= 0 for i in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("artifact_cleanup_invalid_artifact_identity")
    return items


def cleanup(token: str, *, repository: str, dry_run: bool = False) -> dict:
    if repository != REPOSITORY or not token:
        raise RuntimeError("artifact_cleanup_identity_or_auth_missing")
    inventory = list_all(token)
    matches = [x for x in inventory if should_delete(x.get("name"))]
    if not dry_run:
        # The complete deletion plan is established before the first write.
        for item in matches:
            _api("DELETE", f"{API_ROOT}/{item['id']}", token)
        remaining = list_all(token)
        if any(should_delete(x.get("name")) for x in remaining):
            raise RuntimeError("artifact_cleanup_postdelete_risk_remains")
    else:
        remaining = inventory
    return {
        "status": "dry_run" if dry_run else "green",
        "initial_artifacts": len(inventory),
        "sensitive_candidates": len(matches),
        "deleted": 0 if dry_run else len(matches),
        "remaining_artifacts": len(remaining),
        "remaining_suspected_sensitive": (
            len(matches) if dry_run else 0
        ),
        "aggregate_only_artifacts_preserved": sum(
            not should_delete(x.get("name")) for x in remaining
        ),
        "automatic_send": False,
        "changes_campaigns": False,
        "changes_contacts": False,
    }


def main() -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    result = cleanup(token, repository=repository)
    # Print only aggregate counts, not artifact names or IDs.
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
