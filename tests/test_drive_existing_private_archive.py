"""Offline Drive-archive tests. No Google/IMAP network access."""
import io
import hashlib
import json
import unittest
import zipfile

from drive_existing_private_archive import ExistingPrivateArchive


def packed(status, count=0):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as out:
        out.writestr("manifest.json", json.dumps({
            "format": "webactueel-mijnhost-mime-archive-v1",
            "status": status, "messages": count}))
        if count:
            out.writestr("originals/uid-7.eml", b"From: example.invalid\r\n\r\nBody")
    return data.getvalue()


class Response:
    def __init__(self, status=200, data=None, content=b""):
        self.status_code = status
        self.data = data
        self.content = content

    def json(self):
        return self.data


class FakeDriveSession:
    def __init__(self, folder, file_id):
        self.folder = folder
        self.file_id = file_id
        self.bytes = packed("empty-bootstrap")
        self.uploads = 0
        self.public = False

    def get(self, url, params=None, timeout=None):
        if params.get("alt") == "media":
            return Response(content=self.bytes)
        return Response(data={
            "id": self.file_id, "trashed": False,
            "parents": [self.folder], "mimeType": "application/zip",
            "capabilities": {"canEdit": True},
            "permissions": ([{"type": "anyone", "role": "reader"}]
                            if self.public else [{"type": "user", "role": "writer"}]),
        })

    def patch(self, url, params=None, data=None, headers=None, timeout=None):
        self.bytes = data
        self.uploads += 1
        return Response()


class ExistingArchiveTests(unittest.TestCase):
    def setUp(self):
        self.file_id = "A" * 30
        self.folder = "B" * 30
        self.session = FakeDriveSession(self.folder, self.file_id)
        self.archive = ExistingPrivateArchive(self.file_id, self.folder,
                                               session=self.session,
                                               bootstrap_sha=hashlib.sha256(self.session.bytes).hexdigest())

    def test_write_complete_once_and_readback(self):
        content = packed("complete", 1)
        self.assertEqual(self.archive.read_bytes(), self.session.bytes)
        self.assertTrue(self.archive.replace_empty_with(content))
        self.assertEqual(self.archive.read_bytes(), content)
        self.assertEqual(self.session.uploads, 1)
        with self.assertRaisesRegex(RuntimeError, "already_contains"):
            self.archive.replace_empty_with(content)
        self.assertEqual(self.session.uploads, 1)

    def test_public_file_blocked(self):
        self.session.public = True
        with self.assertRaisesRegex(RuntimeError, "visibility"):
            self.archive.read_bytes()
        self.assertEqual(self.session.uploads, 0)

    def test_wrong_folder_blocked(self):
        self.session.folder = "C" * 30
        with self.assertRaisesRegex(RuntimeError, "target_unverified"):
            self.archive.read_bytes()
        self.assertEqual(self.session.uploads, 0)


if __name__ == "__main__":
    unittest.main()
