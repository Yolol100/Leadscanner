import io
import json
import unittest
import zipfile

from preview_snapshot import (
    _snapshot_from_zip,
    build_snapshot,
    materialize_snapshot,
    preview_id_for,
    validate_snapshot,
)
from review_draft_stages import prepare_review_batch
from review_selection import build_review_queue


def candidate():
    return {
        "name_hint": "Acme Fietsen",
        "official_domain": "acmefietsen.nl",
        "official_url": "https://acmefietsen.nl/",
        "public_business_email": "info@acmefietsen.nl",
        "subject": "idee voor jullie afspraakroute",
        "body": "Hallo,\n\nExacte body.\n\nGroet,\nAndrew",
        "mail_status": "ready_for_human_review",
        "copy_validation_status": "green",
        "automatic_send": False,
        "verified_observation": "Klanten kunnen online een afspraak aanvragen.",
        "verified_observation_source_url": "https://acmefietsen.nl/afspraak",
        "verified_observation_source_type": "official_site",
        "signal_type": "appointment",
        "value_first_action": "een korte voorbeeldvariant voor de afspraakroute",
    }


def snapshot():
    batch = prepare_review_batch({"candidates": [candidate()]})
    queue = build_review_queue(batch)
    manifest = {
        "execution_mode": "preview",
        "closure": {
            "status": "preview_ready",
            "mailbox_mutation": False,
            "registry_mutation": False,
            "automatic_send": False,
            "smtp_send": "not_available",
        },
        "counts": {"review_queue_candidates": 1},
        "request": {"region": "Rotterdam"},
    }
    return build_snapshot(
        request={"execution_mode": "preview", "region": "Rotterdam"},
        batch=batch,
        queue=queue,
        manifest=manifest,
        source={
            "repository": "Yolol100/Leadscanner",
            "run_id": 12345,
            "run_number": 678,
            "head_sha": "a" * 40,
        },
    )


class PreviewSnapshotTests(unittest.TestCase):
    def test_snapshot_is_digest_bound_to_exact_review_copy(self):
        first = snapshot()
        self.assertRegex(first["preview_id"], r"^preview-[0-9a-f]{24}$")
        self.assertEqual(first["preview_id"], preview_id_for(first))

        changed = json.loads(json.dumps(first))
        changed["review_draft_batch"]["rows"][0]["body"] += "\nchanged"
        self.assertNotEqual(first["preview_id"], preview_id_for(changed))
        with self.assertRaisesRegex(ValueError, "digest_mismatch"):
            validate_snapshot(changed)

    def test_snapshot_validates_source_run_and_repo(self):
        item = snapshot()
        validate_snapshot(
            item,
            repository="Yolol100/Leadscanner",
            run_id=12345,
            head_sha="a" * 40,
        )
        with self.assertRaisesRegex(ValueError, "repository_mismatch"):
            validate_snapshot(item, repository="Other/Repo")
        with self.assertRaisesRegex(ValueError, "run_id_mismatch"):
            validate_snapshot(item, run_id=999)

    def test_snapshot_rejects_preview_manifest_with_mutation_or_count_drift(self):
        item = snapshot()
        manifest = json.loads(json.dumps(item["preview_manifest"]))
        batch = item["review_draft_batch"]
        queue = item["review_queue"]
        source = item["source"]
        request = item["request"]

        manifest["closure"]["mailbox_mutation"] = True
        with self.assertRaisesRegex(ValueError, "preview_manifest_must_be_mutation_free"):
            build_snapshot(
                request=request,
                batch=batch,
                queue=queue,
                manifest=manifest,
                source=source,
            )

        manifest = json.loads(json.dumps(item["preview_manifest"]))
        manifest["counts"]["review_queue_candidates"] = 0
        with self.assertRaisesRegex(ValueError, "preview_manifest_review_count_mismatch"):
            build_snapshot(
                request=request,
                batch=batch,
                queue=queue,
                manifest=manifest,
                source=source,
            )

    def test_snapshot_rejects_review_token_drift(self):
        item = snapshot()
        item["review_queue"]["items"][0]["approval_token"] = "growth-" + "0" * 20 + "@" + "0" * 16
        item["preview_id"] = preview_id_for(item)
        with self.assertRaisesRegex(ValueError, "approval_token_mismatch"):
            validate_snapshot(item)

    def test_zip_reader_rejects_path_traversal(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as zf:
            zf.writestr("../preview-snapshot.json", json.dumps(snapshot()))
        with self.assertRaisesRegex(RuntimeError, "unsafe_preview_artifact_path"):
            _snapshot_from_zip(raw.getvalue())

    def test_zip_reader_loads_single_snapshot(self):
        item = snapshot()
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as zf:
            zf.writestr("preview-snapshot.json", json.dumps(item))
        loaded = _snapshot_from_zip(raw.getvalue())
        self.assertEqual(loaded["preview_id"], item["preview_id"])

    def test_materialize_writes_only_snapshot_bound_inputs(self):
        import tempfile
        from pathlib import Path

        item = snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            info = materialize_snapshot(item, output_dir=Path(tmp))
            self.assertEqual(info["source_run_id"], 12345)
            batch = json.loads(Path(tmp, "review-draft-batch.json").read_text())
            queue = json.loads(Path(tmp, "review-queue.json").read_text())
            self.assertEqual(batch["draft_candidate_count"], 1)
            self.assertEqual(queue["review_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
