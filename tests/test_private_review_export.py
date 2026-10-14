import base64
from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import private_review_export as export


class PrivateReviewTests(unittest.TestCase):
    def test_envelope_roundtrip_no_plaintext(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        report = {"candidates": [{"company": "Private Bakery", "website_hint": "https://private.test"}]}
        blob = export.seal_report(report, public_pem=pem)
        self.assertNotIn("Private Bakery", blob)
        packed = json.loads(base64.b64decode(blob))
        key = private.decrypt(base64.b64decode(packed["key"]), padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        clear = AESGCM(key).decrypt(base64.b64decode(packed["nonce"]),
                                    base64.b64decode(packed["ciphertext"]), b"lead-review-v1")
        self.assertEqual(json.loads(clear), report)

    def test_failure_fails_closed_without_identity_logging(self):
        with patch.object(export, "run", side_effect=RuntimeError("sensitive@private.test")):
            output = StringIO()
            with redirect_stdout(output):
                code = export.main()
        self.assertEqual(code, 1)
        self.assertNotIn("sensitive@", output.getvalue())
        self.assertIn("ENCRYPTED_LEAD_REVIEW_RESULT=blocked", output.getvalue())


if __name__ == "__main__":
    unittest.main()
