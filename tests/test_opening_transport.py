import unittest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from opening_transport import seal, unseal, public, server_private

class OpeningTransportTests(unittest.TestCase):
    def test_research_and_full_draft_evidence_stay_encrypted_and_readable_by_both_peers(self):
        server = server_private('test-only-credential', 'owner/repo')
        client = X25519PrivateKey.generate()
        body = {'lead_id':'private-lead', 'body':'private-draft-body', 'mode':'apply'}
        envelope = seal(body,client,public(server),'owner/repo','request')
        self.assertNotIn('private-lead',str(envelope))
        self.assertNotIn('private-draft-body',str(envelope))
        self.assertEqual(unseal(envelope,server,'owner/repo','request'),body)
        report = seal(body,server,public(client),'owner/repo','report')
        self.assertEqual(unseal(report,client,'owner/repo','report'),body)
        self.assertEqual(unseal(report,server,'owner/repo','report'),body)
        with self.assertRaises(InvalidTag):unseal(report,client,'owner/repo','request')
        with self.assertRaises(InvalidTag):unseal(report,client,'other/repo','report')
        with self.assertRaises(ValueError):unseal(report,X25519PrivateKey.generate(),'owner/repo','report')

    def test_tamper_and_empty_runtime_secret_fail_closed(self):
        a,b=X25519PrivateKey.generate(),X25519PrivateKey.generate()
        e=seal({'observation':'private'},a,public(b),'owner/repo','request')
        e['nonce']='AAAAAAAAAAAAAAAA'
        with self.assertRaises(InvalidTag):unseal(e,b,'owner/repo','request')
        with self.assertRaises(ValueError):server_private('', 'owner/repo')
