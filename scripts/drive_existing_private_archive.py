"""Validate an existing, privately shared Drive archive before any mailbox read.

The archive must be owned by a human Google account and shared with the
Leadscanner service account; do not create files using service-account quota.
No IMAP, SMTP, public logs, or mailbox mutations here.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
import zipfile

_ID = re.compile(r"[A-Za-z0-9_-]{15,128}\Z")
_DRIVE_URL = "https://www.googleapis.com/drive/v3/files/"


def service_session():
    raw = (os.getenv("LEAD_REGISTRY_SERVICE_ACCOUNT_JSON", "").strip()
           or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip())
    if not raw:
        raise RuntimeError("archive_credentials_missing")
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
        info = json.loads(raw)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive"])
        return AuthorizedSession(credentials)
    except Exception:
        raise RuntimeError("archive_credentials_unusable") from None


class ExistingPrivateArchive:
    def __init__(self, file_id, folder_id, session=None, bootstrap_sha="1a2452da9a1446895864506b65da3a5431953c57cb5474048a7495ef7ec4a983"):
        if not _ID.fullmatch(str(file_id)) or not _ID.fullmatch(str(folder_id)):
            raise RuntimeError("archive_ids_invalid")
        self.file_id, self.folder_id = file_id, folder_id
        self.session = session if session is not None else service_session()
        self.bootstrap_sha = bootstrap_sha

    def inspect(self):
        response = self.session.get(_DRIVE_URL + self.file_id,
            params={"fields": "id,name,mimeType,parents,trashed,capabilities/canEdit,permissions(type,role)"},
            timeout=25)
        if response.status_code != 200:
            raise RuntimeError("archive_access_unavailable")
        data = response.json()
        if (data.get("id") != self.file_id or data.get("trashed") is not False
                or self.folder_id not in (data.get("parents") or [])
                or data.get("mimeType") != "application/zip"
                or not (data.get("capabilities") or {}).get("canEdit")):
            raise RuntimeError("archive_target_unverified")
        permissions = data.get("permissions")
        if not isinstance(permissions, list) or any(
                p.get("type") in ("anyone", "domain") for p in permissions):
            raise RuntimeError("archive_visibility_unverified")
        return True

    def read_bytes(self):
        self.inspect()
        response = self.session.get(_DRIVE_URL + self.file_id,
                                    params={"alt": "media"}, timeout=60)
        if response.status_code != 200 or len(response.content) > 100_000_000:
            raise RuntimeError("archive_read_failed")
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != "webactueel-mijnhost-mime-archive-v1":
                    raise ValueError("wrong manifest")
        except (ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
            raise RuntimeError("archive_manifest_invalid") from None
        return response.content

    def replace_empty_with(self, replacement):
        original = self.read_bytes()
        with zipfile.ZipFile(io.BytesIO(original)) as src:
            if json.loads(src.read("manifest.json")).get("status") != "empty-bootstrap":
                raise RuntimeError("archive_already_contains_records")
        if hashlib.sha256(original).hexdigest() != self.bootstrap_sha:
            raise RuntimeError("archive_bootstrap_changed")
        if not isinstance(replacement, bytes) or not 100 < len(replacement) <= 100_000_000:
            raise RuntimeError("archive_replacement_invalid")
        with zipfile.ZipFile(io.BytesIO(replacement)) as source:
            manifest = json.loads(source.read("manifest.json"))
            if manifest.get("status") != "complete" or not manifest.get("messages"):
                raise RuntimeError("archive_replacement_not_complete")
        response = self.session.patch(
            "https://www.googleapis.com/upload/drive/v3/files/" + self.file_id,
            params={"uploadType": "media"}, data=replacement,
            headers={"Content-Type": "application/zip"}, timeout=120)
        if response.status_code != 200:
            raise RuntimeError("archive_upload_failed")
        if hashlib.sha256(self.read_bytes()).digest() != hashlib.sha256(replacement).digest():
            raise RuntimeError("archive_readback_mismatch")
        return True
