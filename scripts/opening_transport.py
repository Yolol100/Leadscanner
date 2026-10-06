"""Encrypted research requests and exact mailbox evidence over public transport."""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VERSION = 'leadscanner-opening-v1'

def b64(data):
    return base64.b64encode(data).decode('ascii')

def unb64(value):
    return base64.b64decode(value, validate=True)

def server_private(secret, repository):
    if not secret or not repository:
        raise ValueError('existing private runtime credential and repository required')
    seed = Scrypt(salt=(VERSION + ':' + repository).encode(), length=32, n=2**15, r=8, p=1).derive(secret.encode())
    return X25519PrivateKey.from_private_bytes(seed)

def public(private):
    return b64(private.public_key().public_bytes_raw())

def key(private, peer, repository, kind):
    shared = private.exchange(X25519PublicKey.from_public_bytes(unb64(peer)))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
        info=(VERSION + ':' + repository + ':' + kind).encode()).derive(shared)

def seal(value, private, peer, repository, kind):
    nonce = os.urandom(12)
    aad = (VERSION + ':' + repository + ':' + kind).encode()
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    return {'version': VERSION, 'sender': public(private), 'recipient': peer,
        'nonce': b64(nonce), 'ciphertext': b64(AESGCM(key(private, peer, repository, kind)).encrypt(nonce, data, aad))}

def unseal(envelope, private, repository, kind):
    if envelope.get('version') != VERSION:
        raise ValueError('unsupported encrypted transport version')
    own = public(private)
    if own == envelope['recipient']:
        peer = envelope['sender']
    elif own == envelope['sender']:
        peer = envelope['recipient']
    else:
        raise ValueError('encrypted evidence is bound to a different key')
    aad = (VERSION + ':' + repository + ':' + kind).encode()
    data = AESGCM(key(private, peer, repository, kind)).decrypt(unb64(envelope['nonce']), unb64(envelope['ciphertext']), aad)
    return json.loads(data)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['resolve', 'decode-audit', 'publish'])
    args = p.parse_args()
    root = Path('results'); root.mkdir(exist_ok=True)
    repo = os.environ['GITHUB_REPOSITORY']
    private = server_private(os.environ.get('OUTREACH_MAIL_PASSWORD'), repo)
    if args.command == 'resolve':
        raw = json.loads(json.loads(Path(os.environ['EVENT_PATH']).read_text())['issue']['body'])
        if raw == {'mode': 'transport-key'}:
            (root/'public-key.json').write_text(json.dumps({'version': VERSION, 'repository': repo, 'public_key': public(private)}))
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:f.write('is_key=true\n')
            return
        if raw.get('mode') != 'encrypted' or raw.get('operation') not in {'audit','apply','final'}:
            raise ValueError('research requests require encrypted transport')
        envelope = raw['payload']
        if envelope.get('recipient') != public(private) or len(json.dumps(envelope)) > 200000:
            raise ValueError('invalid recipient or oversized encrypted request')
        req = unseal(envelope, private, repo, 'request')
        if req.get('mode') != raw['operation']:
            raise ValueError('encrypted operation mismatch')
        from myhost_opening_remediation import validate_request
        validate_request(req)
        (root/'request.json').write_text(json.dumps(req, ensure_ascii=False))
        (root/'transport.json').write_text(json.dumps(envelope))
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:f.write('is_key=false\n')
    elif args.command == 'decode-audit':
        enc = root/'audit/opening-report.enc.json'
        if enc.exists():
            (root/'audit/opening-report.json').write_text(json.dumps(unseal(json.loads(enc.read_text()),private,repo,'report'),ensure_ascii=False))
    elif args.command == 'publish':
        report = root/'opening-report.json'
        if not report.exists():return
        r = json.loads(report.read_text())
        transport = json.loads((root/'transport.json').read_text())
        (root/'opening-report.enc.json').write_text(json.dumps(seal(r,private,transport['sender'],repo,'report')))
        safe = {k:r.get(k) for k in ('mode','audited_count','ready_count','hold_count','absent_count','changed_count','already_correct_count','removed_count','automatic_send','send_capability')}
        safe['blocker_count'] = len(r.get('blockers',[]))
        (root/'summary.json').write_text(json.dumps(safe))

if __name__ == '__main__':main()
