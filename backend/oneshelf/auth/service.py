"""Remote Web UI authentication (Master §28).

This ties the three pieces together and owns the trust rules:

- Local and LAN access is unauthenticated by default; genuine LAN devices are fully trusted (§28.1).
- Remote access is passkey-only, on the canonical HTTPS hostname (§28.3).
- Registering a passkey needs a real authorization: genuine LAN, a valid Recovery Code, or an existing
  remote session. A remote client can never bootstrap itself.
- LAN Recovery clears passkeys and remote sessions and nothing else (§28.5).
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from oneshelf.auth.passkeys import Ceremony, Credential, PasskeyService
from oneshelf.auth.recovery import RecoveryCodes
from oneshelf.auth.sessions import DEFAULT_LIFETIME, IssuedSession, RemoteSessions
from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso

HOSTNAME_SETTING = "remote.canonical_hostname"
HOSTNAME_PATTERN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z]{2,63}$")
TRUSTED_ACCESS = ("loopback", "lan")

LAN_RECOVERY_MESSAGE = (
    "This resets remote Web UI authentication only: every passkey is removed and every remote session is "
    "signed out. Your library, Shelf, reading progress, downloads, plugins, source sessions and content are "
    "not affected."
)


class RemoteAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class Enrolment:
    credential: Credential
    recovery_code: str | None


@dataclass(frozen=True)
class RecoveryReport:
    passkeys_removed: int
    sessions_revoked: int
    message: str


class RemoteAuth:
    def __init__(self, conn: sqlite3.Connection, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.conn = conn
        self.clock = clock
        self.sessions = RemoteSessions(conn, clock=clock)
        self.recovery = RecoveryCodes(conn, clock=clock)

    # -- canonical hostname -------------------------------------------------------------------------

    @property
    def canonical_hostname(self) -> str | None:
        row = self.conn.execute("SELECT value_json FROM settings WHERE scope = 'global' AND scope_id = ''"
                                " AND key = ?", (HOSTNAME_SETTING,)).fetchone()
        return json.loads(row[0]) if row is not None else None

    def set_canonical_hostname(self, value: str) -> str:
        host = (value or "").strip().lower()
        host = re.sub(r"^https?://", "", host).rstrip("/").split("/")[0].rsplit(":", 1)[0].rstrip(".")
        if not HOSTNAME_PATTERN.match(host):
            raise RemoteAuthError("enter the hostname people will use to reach OneShelf, for example "
                                  "oneshelf.example.net")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO settings (scope, scope_id, key, value_json, updated_at) VALUES ('global','',?,?,?)"
                " ON CONFLICT(scope, scope_id, key) DO UPDATE SET value_json = excluded.value_json,"
                " updated_at = excluded.updated_at", (HOSTNAME_SETTING, json.dumps(host), utcnow_iso()))
        return host

    @property
    def passkeys(self) -> PasskeyService:
        host = self.canonical_hostname
        if not host:
            raise RemoteAuthError("set the canonical HTTPS hostname before using passkeys")
        return PasskeyService(self.conn, rp_id=host, origin=f"https://{host}", clock=self.clock)

    # -- registration -------------------------------------------------------------------------------

    def _authorization(self, *, access: str, recovery_code: str | None, session_token: str | None) -> str:
        if access in TRUSTED_ACCESS:
            return "lan"
        if recovery_code and self.recovery.verify(recovery_code):
            return "recovery"
        if session_token and self.sessions.validate(session_token):
            return "session"
        raise RemoteAuthError("registering a passkey needs LAN access, a valid Recovery Code, or a signed-in "
                              "remote session")

    def begin_registration(self, *, access: str, label: str = "Passkey", recovery_code: str | None = None,
                           session_token: str | None = None) -> Ceremony:
        authorized_by = self._authorization(access=access, recovery_code=recovery_code, session_token=session_token)
        return self.passkeys.registration_options(authorized_by=authorized_by)

    def complete_registration(self, ceremony_id: str, response: dict, *, label: str = "Passkey") -> Enrolment:
        first_passkey = not self.passkeys.list_credentials()
        used_recovery = self._pending_authorization(ceremony_id) == "recovery"
        credential = self.passkeys.verify_registration(ceremony_id, response, label=label)
        if used_recovery:
            self.recovery.mark_used()
        code = self.recovery.generate() if first_passkey else None   # §28.5: issued with the first passkey
        return Enrolment(credential, code)

    def _pending_authorization(self, ceremony_id: str) -> str | None:
        row = self.conn.execute("SELECT authorized_by FROM webauthn_challenges WHERE id = ?",
                                (ceremony_id,)).fetchone()
        return row["authorized_by"] if row else None

    def regenerate_recovery_code(self) -> str:
        """A new code invalidates the previous one (§28.5)."""
        return self.recovery.generate()

    # -- authentication -----------------------------------------------------------------------------

    def begin_authentication(self) -> Ceremony:
        return self.passkeys.authentication_options()

    def complete_authentication(self, ceremony_id: str, response: dict, *, label: str = "Remote device",
                                lifetime: str = DEFAULT_LIFETIME) -> IssuedSession:
        self.passkeys.verify_authentication(ceremony_id, response)
        return self.sessions.create(label=label, lifetime=lifetime)

    def sign_out(self, token: str | None) -> bool:
        session = self.sessions.validate(token)
        return self.sessions.revoke(session.id) if session else False

    # -- LAN recovery -------------------------------------------------------------------------------

    def lan_recovery_reset(self, *, access: str) -> RecoveryReport:
        """§28.5: only a genuine trusted LAN (or the host itself) may reset remote authentication."""
        if access not in TRUSTED_ACCESS:
            raise RemoteAuthError("LAN Recovery is only available from a device on your trusted network")
        removed = 0
        try:
            removed = self.passkeys.reset()
        except RemoteAuthError:
            pass                                     # no hostname configured yet: nothing to remove
        revoked = self.sessions.revoke_all()
        with transaction(self.conn):
            self.conn.execute("DELETE FROM remote_recovery")
        return RecoveryReport(removed, revoked, LAN_RECOVERY_MESSAGE)

    # -- state --------------------------------------------------------------------------------------

    def state(self) -> dict:
        host = self.canonical_hostname
        credentials = self.passkeys.list_credentials() if host else []
        return {
            "canonical_hostname": host,
            "remote_enabled": bool(host and credentials),
            "passkeys": [{"credential_id": c.credential_id, "label": c.label, "created_at": c.created_at,
                          "last_used_at": c.last_used_at, "backed_up": c.backed_up} for c in credentials],
            "recovery": self.recovery.status(),
            "sessions": [{"id": s.id, "label": s.label, "created_at": s.created_at,
                          "last_active_at": s.last_active_at, "expires_at": s.expires_at, "current": s.current}
                         for s in self.sessions.list_sessions()],
        }
