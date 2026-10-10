#!/usr/bin/env python3
"""Phases 19-20: immutable preview snapshots and fast draft resume."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path

import requests

from review_selection import review_token

SCHEMA = "leadscanner-preview-snapshot/1.0"
MAX_ARCHIVE_BYTES = 25_000_000
MAX_MEMBER_BYTES = 10_000_000
API_VERSION = "2022-11-28"


def _text(value: object) -> str:
    return str(value or "").strip()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _snapshot_core(snapshot: dict) -> dict:
    return {
        "schema_version": snapshot.get("schema_version"),
        "source": snapshot.get("source"),
        "request": snapshot.get("request"),
        "review_draft_batch": snapshot.get("review_draft_batch"),
        "review_queue": snapshot.get("review_queue"),
        "preview_manifest": snapshot.get("preview_manifest"),
    }


def preview_id_for(snapshot: dict) -> str:
    digest = hashlib.sha256(_canonical(_snapshot_core(snapshot))).hexdigest()[:24]
    return f"preview-{digest}"


def build_snapshot(*, request: dict, batch: dict, queue: dict, manifest: dict, source: dict) -> dict:
    if manifest.get("execution_mode") != "preview":
        raise ValueError("snapshot_requires_preview_manifest")
    closure = manifest.get("closure") or {}
    if closure.get("status") != "preview_ready":
        raise ValueError("snapshot_requires_preview_ready_closure")
    if (
        closure.get("mailbox_mutation") is not False
        or closure.get("registry_mutation") is not False
        or closure.get("automatic_send") is not False
        or closure.get("smtp_send") != "not_available"
    ):
        raise ValueError("preview_manifest_must_be_mutation_free")
    if batch.get("draft_candidate_count") != queue.get("review_candidate_count"):
        raise ValueError("snapshot_review_count_mismatch")
    if int((manifest.get("counts") or {}).get("review_queue_candidates") or 0) != int(
        queue.get("review_candidate_count") or 0
    ):
        raise ValueError("preview_manifest_review_count_mismatch")

    rows = batch.get("rows") or []
    items = queue.get("items") or []
    if len(rows) != len(items):
        raise ValueError("snapshot_row_item_count_mismatch")
    by_lead = {_text(row.get("lead_id")): row for row in rows}
    if len(by_lead) != len(rows):
        raise ValueError("snapshot_duplicate_lead_id")
    for item in items:
        lead_id = _text(item.get("lead_id"))
        row = by_lead.get(lead_id)
        if row is None:
            raise ValueError("snapshot_queue_lead_missing_from_batch")
        if _text(item.get("approval_token")) != review_token(row):
            raise ValueError("snapshot_approval_token_mismatch")

    repository = _text(source.get("repository"))
    run_id = int(source.get("run_id") or 0)
    run_number = int(source.get("run_number") or 0)
    head_sha = _text(source.get("head_sha"))
    if not repository or run_id <= 0 or run_number <= 0 or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise ValueError("snapshot_source_metadata_invalid")

    snapshot = {
        "schema_version": SCHEMA,
        "source": {
            "repository": repository,
            "run_id": run_id,
            "run_number": run_number,
            "head_sha": head_sha,
        },
        "request": request,
        "review_draft_batch": batch,
        "review_queue": queue,
        "preview_manifest": manifest,
    }
    snapshot["preview_id"] = preview_id_for(snapshot)
    return snapshot


def validate_snapshot(snapshot: dict, *, repository: str | None = None, run_id: int | None = None, head_sha: str | None = None) -> dict:
    if snapshot.get("schema_version") != SCHEMA:
        raise ValueError("preview_snapshot_schema_mismatch")
    expected_id = preview_id_for(snapshot)
    if snapshot.get("preview_id") != expected_id:
        raise ValueError("preview_snapshot_digest_mismatch")

    source = snapshot.get("source") or {}
    if repository and _text(source.get("repository")) != repository:
        raise ValueError("preview_snapshot_repository_mismatch")
    if run_id is not None and int(source.get("run_id") or 0) != int(run_id):
        raise ValueError("preview_snapshot_run_id_mismatch")
    if head_sha and _text(source.get("head_sha")) != head_sha:
        raise ValueError("preview_snapshot_head_sha_mismatch")

    build_snapshot(
        request=snapshot.get("request") or {},
        batch=snapshot.get("review_draft_batch") or {},
        queue=snapshot.get("review_queue") or {},
        manifest=snapshot.get("preview_manifest") or {},
        source=source,
    )
    return snapshot


def _github_headers(token: str) -> dict:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to resume a preview artifact")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "Leadscanner/preview-resume",
    }


def _get_json(session, url: str, headers: dict) -> dict:
    response = session.get(url, headers=headers, timeout=20)
    if response.status_code != 200:
        raise RuntimeError(f"github_api_read_failed status={response.status_code} url={url}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("github_api_returned_non_object")
    return payload


def _snapshot_from_zip(raw: bytes) -> dict:
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise RuntimeError("preview_artifact_archive_too_large")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 100:
            raise RuntimeError("preview_artifact_too_many_files")
        target = None
        for member in members:
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimeError("unsafe_preview_artifact_path")
            if member.file_size > MAX_MEMBER_BYTES:
                raise RuntimeError("preview_artifact_member_too_large")
            if path.name == "preview-snapshot.json":
                if target is not None:
                    raise RuntimeError("multiple_preview_snapshots_in_artifact")
                target = member
        if target is None:
            raise RuntimeError("preview_snapshot_missing_from_artifact")
        with archive.open(target) as handle:
            payload = json.loads(handle.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("preview_snapshot_must_be_object")
    return payload


def fetch_snapshot(*, repository: str, run_id: int, token: str, session=requests) -> dict:
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise ValueError("repository_must_be_owner_name")
    if run_id <= 0:
        raise ValueError("preview_run_id_must_be_positive")

    headers = _github_headers(token)
    base = f"https://api.github.com/repos/{repository}"
    run = _get_json(session, f"{base}/actions/runs/{run_id}", headers)
    if run.get("event") != "workflow_dispatch":
        raise RuntimeError("source_preview_must_be_workflow_dispatch")
    if run.get("conclusion") != "success":
        raise RuntimeError("source_preview_run_not_successful")
    if run.get("head_branch") != "main":
        raise RuntimeError("source_preview_must_be_from_main")
    head_sha = _text(run.get("head_sha"))
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise RuntimeError("source_preview_head_sha_invalid")

    artifact_name = f"leads-cold-preview-{run_id}"
    listing = _get_json(
        session,
        f"{base}/actions/runs/{run_id}/artifacts?name={artifact_name}&per_page=100",
        headers,
    )
    artifacts = [
        item for item in (listing.get("artifacts") or [])
        if item.get("name") == artifact_name and not item.get("expired")
    ]
    if len(artifacts) != 1:
        raise RuntimeError(
            f"expected_one_live_preview_artifact found={len(artifacts)} name={artifact_name}"
        )

    artifact_id = int(artifacts[0].get("id") or 0)
    if artifact_id <= 0:
        raise RuntimeError("preview_artifact_id_invalid")
    response = session.get(
        f"{base}/actions/artifacts/{artifact_id}/zip",
        headers=headers,
        timeout=30,
        allow_redirects=True,
    )
    if response.status_code != 200:
        raise RuntimeError(f"preview_artifact_download_failed status={response.status_code}")
    snapshot = _snapshot_from_zip(response.content)
    return validate_snapshot(
        snapshot,
        repository=repository,
        run_id=run_id,
        head_sha=head_sha,
    )


def materialize_snapshot(snapshot: dict, *, output_dir: Path) -> dict:
    validate_snapshot(snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "review-draft-batch.json": snapshot["review_draft_batch"],
        "review-queue.json": snapshot["review_queue"],
        "source-preview-manifest.json": snapshot["preview_manifest"],
        "source-preview-request.json": snapshot["request"],
        "preview-snapshot.json": snapshot,
    }
    for name, payload in outputs.items():
        (output_dir / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {
        "preview_id": snapshot["preview_id"],
        "source_run_id": snapshot["source"]["run_id"],
        "source_head_sha": snapshot["source"]["head_sha"],
        "review_candidate_count": snapshot["review_queue"]["review_candidate_count"],
    }


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input_must_be_object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--request", required=True)
    build.add_argument("--batch", required=True)
    build.add_argument("--queue", required=True)
    build.add_argument("--manifest", required=True)
    build.add_argument("--output", required=True)

    resume = sub.add_parser("resume")
    resume.add_argument("--run-id", type=int, required=True)
    resume.add_argument("--output-dir", required=True)

    args = parser.parse_args()
    if args.command == "build":
        source = {
            "repository": os.getenv("GITHUB_REPOSITORY", ""),
            "run_id": os.getenv("GITHUB_RUN_ID", ""),
            "run_number": os.getenv("GITHUB_RUN_NUMBER", ""),
            "head_sha": os.getenv("GITHUB_SHA", ""),
        }
        snapshot = build_snapshot(
            request=_load(args.request),
            batch=_load(args.batch),
            queue=_load(args.queue),
            manifest=_load(args.manifest),
            source=source,
        )
        Path(args.output).write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            "PREVIEW_SNAPSHOT=green "
            f"preview_id={snapshot['preview_id']} "
            f"run_id={snapshot['source']['run_id']} "
            f"review_candidates={snapshot['review_queue']['review_candidate_count']}"
        )
    else:
        repository = os.getenv("GITHUB_REPOSITORY", "")
        token = os.getenv("GITHUB_TOKEN", "")
        snapshot = fetch_snapshot(
            repository=repository,
            run_id=args.run_id,
            token=token,
        )
        info = materialize_snapshot(snapshot, output_dir=Path(args.output_dir))
        print(
            "PREVIEW_RESUME=green "
            f"preview_id={info['preview_id']} "
            f"source_run_id={info['source_run_id']} "
            f"review_candidates={info['review_candidate_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
