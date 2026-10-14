import base64
import json
import unittest
import zlib
from unittest.mock import Mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import bulk450_private_export as bulk
from dedupe_preflight import load_registry_values

HEADERS = ["company", "website", "domain", "emails", "status",
           "history", "lead_ids", "last_event_at", "sources",
           "exclude_from_new_leads"]


class Bulk450Tests(unittest.TestCase):
    def test_target_sectors_and_geography(self):
        base = {
            "name_hint": "Studio Knip", "website_hint": "https://studioknip.nl",
            "category_hint": "hair_salon", "country_hint": "NL",
        }
        self.assertEqual(bulk.company_hint(base)[-1], "kappers")
        self.assertIsNone(bulk.company_hint(dict(base, country_hint="DE")))
        self.assertIsNone(bulk.company_hint(dict(base, website_hint="https://studioknip.de")))
        self.assertIsNone(bulk.company_hint(dict(base, website_hint="https://www.amikappers.nl/locatie")))
        self.assertEqual(bulk.sector_for({
            "name_hint": "Bouw BV", "category_hint": "construction_company"
        }), "bouwbedrijven")

    def test_cross_region_dedupe_and_historical_suppression(self):
        registry = load_registry_values([
            HEADERS,
            ["Existing", "https://older.nl", "older.nl",
             "old@example.nl", "sent", "", "prior-id", "", "", "TRUE"],
        ])
        calls = []

        def source(**kw):
            calls.append(kw)
            number = len(calls)
            return {"candidates": [
                {"name_hint": "Existing", "website_hint": "https://older.nl",
                 "category_hint": "hair_salon", "country_hint": "NL",
                 "overture_id": "prior-id"},
                {"name_hint": "Unique " + str(number),
                 "website_hint": "https://unique" + str(number) + ".nl",
                 "category_hint": "construction_company", "country_hint": "NL",
                 "overture_id": "new-id-" + str(number)},
                {"name_hint": "Repeated company", "website_hint": "https://same.nl",
                 "category_hint": "hair_salon", "country_hint": "NL"},
            ]}
        pools, stats, failures = bulk.survey(
            registry, source=source, hubs=["Zwolle"] * 12)
        self.assertEqual(stats["historically_suppressed"], 12)
        self.assertEqual(len(pools["bouwbedrijven"]), 12)
        self.assertEqual(len(pools["kappers"]), 1)
        self.assertEqual(stats["hubs_completed"], 12)
        self.assertEqual(failures, [])

    def test_verified_website_filter(self):
        rows = [{"website": "https://a.nl"}, {"website": "https://b.nl"}]
        def probe(url, timeout):
            return {"status": "reachable_needs_leads_identity_verification"
                    if url.endswith("a.nl") else "unreachable",
                    "final_url": url, "http_status": 200 if url.endswith("a.nl") else 404}
        probes = bulk.reachability(rows, probe=probe)
        kept, reachable, failed = bulk.choose_450(rows, probes)
        self.assertEqual((len(kept), reachable, failed), (1, 1, 1))
        self.assertEqual(kept[0]["technical_status"],
                         "reachable_needs_leads_identity_verification")

    def test_ciphertext_roundtrip_no_plaintext(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        plain = {"candidates": [{"company": "SECRET_STUDIO_NAME"}]}
        token = bulk.seal(plain, pub)
        self.assertNotIn("SECRET_STUDIO_NAME", token)
        envelope = json.loads(base64.b64decode(token))
        sym = key.decrypt(base64.b64decode(envelope["key"]), padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(), label=None))
        raw = AESGCM(sym).decrypt(
            base64.b64decode(envelope["nonce"]),
            base64.b64decode(envelope["ciphertext"]), b"fresh-leads-450-v1")
        self.assertEqual(json.loads(zlib.decompress(raw)), plain)

    def test_missing_geographic_coverage_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "insufficient_regional_coverage"):
            bulk.survey([], source=lambda **kw: (_ for _ in ()).throw(RuntimeError("PDOK failed")),
                        hubs=["Zwolle"] * 12)


if __name__ == "__main__":
    unittest.main()
