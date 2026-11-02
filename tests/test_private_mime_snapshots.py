"""Offline regression checks for private snapshot adapter."""
import tempfile
import unittest
from pathlib import Path

from private_mime_snapshots import PrivateMimeSnapshots

DRAFT = "draft-" + "a" * 32


class SnapshotTests(unittest.TestCase):
    def test_roundtrip_idempotent_and_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            root.mkdir(mode=0o700)
            storage = PrivateMimeSnapshots(root)
            raw = b"From: example@example.test\r\nTo: other@example.test\r\n\r\nOriginal"
            key = storage.save(DRAFT, "55", "8", raw)
            self.assertEqual(storage.read(key), raw)
            self.assertEqual(storage.save(DRAFT, "55", "8", raw), key)
            self.assertNotEqual(storage.save(DRAFT, "55", "9", raw), key)
            self.assertEqual((root / key).stat().st_mode & 0o777, 0o600)

    def test_reject_public_directory_and_invalid_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            root.mkdir(mode=0o700)
            root.chmod(0o755)
            with self.assertRaises(RuntimeError):
                PrivateMimeSnapshots(root)
            root.chmod(0o700)
            storage = PrivateMimeSnapshots(root)
            with self.assertRaises(RuntimeError):
                storage.save(DRAFT, "0", "1", b"x")
            with self.assertRaises(RuntimeError):
                storage.read("../escape.eml")


if __name__ == "__main__":
    unittest.main()
