"""A minimal software WebAuthn authenticator (ES256, attestation 'none') for passkey tests."""
import hashlib
import json
import secrets

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from oneshelf.auth.passkeys import b64url


class SoftAuthenticator:
    def __init__(self, *, rp_id: str, origin: str):
        self.rp_id, self.origin = rp_id, origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.sign_count = 0

    def _client_data(self, kind: str, challenge: bytes, origin: str | None = None) -> bytes:
        return json.dumps({"type": kind, "challenge": b64url(challenge), "origin": origin or self.origin,
                           "crossOrigin": False}, separators=(",", ":")).encode()

    def _auth_data(self, *, flags: int, rp_id: str | None = None) -> bytes:
        rp_hash = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        return rp_hash + bytes([flags]) + self.sign_count.to_bytes(4, "big")

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1,
                            -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def register(self, challenge: bytes, *, origin: str | None = None, rp_id: str | None = None) -> dict:
        client_data = self._client_data("webauthn.create", challenge, origin)
        attested = (b"\x00" * 16 + len(self.credential_id).to_bytes(2, "big") + self.credential_id + self._cose_key())
        auth_data = self._auth_data(flags=0x45, rp_id=rp_id) + attested      # UP | UV | AT
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": b64url(self.credential_id), "rawId": b64url(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64url(client_data), "attestationObject": b64url(attestation),
                             "transports": ["internal"]},
                "clientExtensionResults": {}}

    def authenticate(self, challenge: bytes, *, origin: str | None = None, rp_id: str | None = None,
                     sign_count: int | None = None) -> dict:
        self.sign_count = self.sign_count + 1 if sign_count is None else sign_count
        client_data = self._client_data("webauthn.get", challenge, origin)
        auth_data = self._auth_data(flags=0x05, rp_id=rp_id)                 # UP | UV
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64url(self.credential_id), "rawId": b64url(self.credential_id), "type": "public-key",
                "response": {"clientDataJSON": b64url(client_data), "authenticatorData": b64url(auth_data),
                             "signature": b64url(signature), "userHandle": None},
                "clientExtensionResults": {}}
