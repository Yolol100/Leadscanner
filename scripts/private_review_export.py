"""Single-use encrypted transfer of freshly deduplicated leads; no personal public logs.

The matching private key is generated outside GitHub. Do NOT add that key to
this repository or to CI secrets, outputs, or artifacts.
"""
import base64
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
import json
import os
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from new_leads import run
from overture_discovery import probe_candidates

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEA6bYiX4q5NDu8fCPM56ku
4AGVKmm2TpxVIJd6fsaT2PFuB0OMe26PVyzel4c1OBxh6lzp8seJwzIFTg6+l3Da
6YHjgFZy+CDOhTz2jJpwGUpAGCcJHNzTT59lTtc7QGZ4yApaUGHhZ4MtMYK03Mw5
FhEmZXiVygXgpW2xn4T2R2hZVcljv5DWzB0Wz69Opvzf7F/vN4XskwR7PAtDX32Q
+tfBliZuH+25lSQjudMpcyIlYVMvQtr79jtOPz8jg6KoEFyZMQFOg1ea5gvn5qpw
6tYcKJpvMSiv+bMNPjjtOKNo54xERltGnnMgQkTMnbnA+I6pzj3d6X9ScJg1Mish
KvU0BYBJlhZEeBuFJyS+jPLwBhHlhj42rw5dvfJ1Udg4welC6ozdKlX7TmUHY2Bi
f52u6NEvzwv/h1Q5T97HZhKe+9M4BI5JOrjU0FGaQMs4CehTpVJElNb33BNFQQ0+
PyM0LxiEMWgxC6ptrRsYP9LbMa/OO+Yty/7zkXuGZ07vAgMBAAE=
-----END PUBLIC KEY-----""".encode()
MARKER = "ENCRYPTED_LEAD_REVIEW_V1="

def seal_report(report, public_pem=PUBLIC_KEY_PEM):
    public = serialization.load_pem_public_key(public_pem)
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    body = json.dumps(report, ensure_ascii=False, separators=(",", ":")).encode()
    if not body or len(body) > 100_000:
        raise ValueError("unexpected_payload_size")
    ciphertext = AESGCM(key).encrypt(nonce, body, b"lead-review-v1")
    wrapped = public.encrypt(key, padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(), label=None))
    packed = {
        "v": 1,
        "key": base64.b64encode(wrapped).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
    return base64.b64encode(json.dumps(packed,separators=(",",":")).encode()).decode()

def main():
    try:
        # Never expose Overture/PDOK output or source exceptions in public logs.
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            data = run("Nederland", ["kapsalon", "bouwbedrijf"], 25.0, 30)
            if (data["counts"].get("new_unverified_hints") != 30 or
                data["counts"].get("regions_scanned") != 12 or
                len(data["candidates"]) != 30):
                raise RuntimeError("fresh_reconstruction_incomplete")
            probes = probe_candidates(data["candidates"], max_workers=6)
            candidates = []
            for row, proof in zip(data["candidates"], probes):
                candidates.append({
                    "company": row["company"],
                    "website_hint": row["website_hint"],
                    "probe_status": proof.get("status"),
                    "final_url": proof.get("final_url"),
                    "http_status": proof.get("http_status"),
                    "verification": "automatic_reachability_only",
                })
            package = {
                "source": "Overture/PDOK via Leadscanner",
                "reconstructed_utc": datetime.now(timezone.utc).isoformat(),
                "region": "12_provincial_samples_not_national_census",
                "branches": ["kapsalon", "bouwbedrijf"],
                "counts": data["counts"],
                "candidates": candidates,
                "note": "Not manually verified; private review required before accepting leads",
            }
        ciphertext = seal_report(package)
        print(MARKER + ciphertext, flush=True)
        print("ENCRYPTED_LEAD_REVIEW_RESULT=success count=30 no_mail=true")
        return 0
    except BaseException:
        print("ENCRYPTED_LEAD_REVIEW_RESULT=blocked details_suppressed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
