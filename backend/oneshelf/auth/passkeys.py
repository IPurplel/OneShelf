"""Passkey (WebAuthn) ceremonies for remote access (Master §28.3–28.4).

Passkeys are bound to the canonical HTTPS hostname. One fixed internal identity is used for every
credential; it is an implementation detail and is never surfaced as an account or profile. Challenges
live in the database, are single-use and short-lived, and registration always needs an authorization
(genuine LAN, a Recovery Code, or an existing remote session).
"""
from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import webauthn
from webauthn.helpers import exceptions as webauthn_exceptions
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from oneshelf.db.connection import transaction
from oneshelf.domain.ids import new_id

# §28.4: one fixed internal identity, never an account.
INTERNAL_USER_ID = b"oneshelf-local-user"
INTERNAL_USER_NAME = "oneshelf"
RP_NAME = "OneShelf"
DISPLAY_NAME = "OneShelf"
CHALLENGE_TTL = timedelta(minutes=5)
AUTHORIZATIONS = ("lan", "recovery", "session")


class PasskeyError(RuntimeError):
    pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class Ceremony:
    id: str
    challenge: bytes
    options: dict


@dataclass(frozen=True)
class Credential:
    credential_id: str
    label: str
    created_at: str
    last_used_at: str | None = None
    backed_up: bool = False


class PasskeyService:
    def __init__(self, conn: sqlite3.Connection, *, rp_id: str, origin: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.conn = conn
        self.rp_id = rp_id
        self.origin = origin
        self.clock = clock

    # -- ceremonies ---------------------------------------------------------------------------------

    def _store_challenge(self, kind: str, challenge: bytes, authorized_by: str | None) -> str:
        ceremony_id, now = new_id(), self.clock()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO webauthn_challenges (id, kind, challenge, authorized_by, created_at, expires_at)"
                " VALUES (?,?,?,?,?,?)",
                (ceremony_id, kind, challenge, authorized_by, now.isoformat(), (now + CHALLENGE_TTL).isoformat()))
        return ceremony_id

    def _take_challenge(self, ceremony_id: str, kind: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM webauthn_challenges WHERE id = ? AND kind = ?",
                                (ceremony_id, kind)).fetchone()
        if row is None:
            raise PasskeyError("this sign-in attempt is no longer valid; start again")
        with transaction(self.conn):           # single use, whatever the outcome
            self.conn.execute("DELETE FROM webauthn_challenges WHERE id = ?", (ceremony_id,))
        if row["expires_at"] <= self.clock().isoformat():
            raise PasskeyError("this sign-in attempt expired; start again")
        return row

    def registration_options(self, *, authorized_by: str) -> Ceremony:
        if authorized_by not in AUTHORIZATIONS:
            raise PasskeyError("registering a passkey needs LAN access, a Recovery Code or a signed-in session")
        existing = [PublicKeyCredentialDescriptor(id=_unb64url(c.credential_id)) for c in self.list_credentials()]
        options = webauthn.generate_registration_options(
            rp_id=self.rp_id, rp_name=RP_NAME, user_id=INTERNAL_USER_ID, user_name=INTERNAL_USER_NAME,
            user_display_name=DISPLAY_NAME, exclude_credentials=existing,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.PREFERRED))
        ceremony_id = self._store_challenge("registration", options.challenge, authorized_by)
        return Ceremony(ceremony_id, options.challenge, json.loads(webauthn.options_to_json(options)))

    def verify_registration(self, ceremony_id: str, response: dict, *, label: str) -> Credential:
        row = self._take_challenge(ceremony_id, "registration")
        try:
            verified = webauthn.verify_registration_response(
                credential=json.dumps(response), expected_challenge=bytes(row["challenge"]),
                expected_rp_id=self.rp_id, expected_origin=self.origin)
        except webauthn_exceptions.InvalidRegistrationResponse as exc:
            raise PasskeyError(f"this passkey could not be registered: {exc}") from exc
        credential_id, now = b64url(verified.credential_id), self.clock().isoformat()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO remote_credentials (credential_id, public_key, sign_count, label, transports,"
                " backed_up, created_at) VALUES (?,?,?,?,?,?,?)",
                (credential_id, verified.credential_public_key, verified.sign_count, label.strip() or "Passkey",
                 json.dumps(response.get("response", {}).get("transports") or []),
                 int(bool(getattr(verified, "credential_backed_up", False))), now))
        return Credential(credential_id, label.strip() or "Passkey", now, None,
                          bool(getattr(verified, "credential_backed_up", False)))

    def authentication_options(self) -> Ceremony:
        if not self.list_credentials():
            raise PasskeyError("no passkey is registered for remote access")
        options = webauthn.generate_authentication_options(
            rp_id=self.rp_id, user_verification=UserVerificationRequirement.PREFERRED)
        ceremony_id = self._store_challenge("authentication", options.challenge, None)
        return Ceremony(ceremony_id, options.challenge, json.loads(webauthn.options_to_json(options)))

    def verify_authentication(self, ceremony_id: str, response: dict) -> Credential:
        row = self._take_challenge(ceremony_id, "authentication")
        stored = self.conn.execute("SELECT * FROM remote_credentials WHERE credential_id = ?",
                                   (response.get("id"),)).fetchone()
        if stored is None:
            raise PasskeyError("this passkey is not registered here")
        try:
            verified = webauthn.verify_authentication_response(
                credential=json.dumps(response), expected_challenge=bytes(row["challenge"]),
                expected_rp_id=self.rp_id, expected_origin=self.origin,
                credential_public_key=bytes(stored["public_key"]),
                credential_current_sign_count=stored["sign_count"])
        except webauthn_exceptions.InvalidAuthenticationResponse as exc:
            raise PasskeyError(f"this passkey could not be verified: {exc}") from exc
        now = self.clock().isoformat()
        with transaction(self.conn):
            self.conn.execute("UPDATE remote_credentials SET sign_count = ?, last_used_at = ? WHERE credential_id = ?",
                              (verified.new_sign_count, now, stored["credential_id"]))
        return Credential(stored["credential_id"], stored["label"], stored["created_at"], now,
                          bool(stored["backed_up"]))

    # -- credentials --------------------------------------------------------------------------------

    def list_credentials(self) -> list[Credential]:
        return [Credential(r["credential_id"], r["label"], r["created_at"], r["last_used_at"], bool(r["backed_up"]))
                for r in self.conn.execute("SELECT * FROM remote_credentials ORDER BY created_at")]

    def delete_credential(self, credential_id: str) -> bool:
        with transaction(self.conn):
            cursor = self.conn.execute("DELETE FROM remote_credentials WHERE credential_id = ?", (credential_id,))
        return cursor.rowcount > 0

    def reset(self) -> int:
        """Removes every passkey (LAN Recovery, §28.5). Library state is not touched."""
        with transaction(self.conn):
            cursor = self.conn.execute("DELETE FROM remote_credentials")
            self.conn.execute("DELETE FROM webauthn_challenges")
        return cursor.rowcount
