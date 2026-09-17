"""Use My Session state machine and request scoping (Master §13).

States: not_connected ↔ checking ↔ connected ↔ needs_reconnect. Plugins never see session material:
Core asks cookie_header() per request, which only returns cookies for declared auth capabilities on
declared session domains while the session is connected.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from collections import defaultdict
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.events.bus import EventBus
from oneshelf.net.domains import host_allowed, to_ascii_host
from oneshelf.plugins.schema import Auth
from oneshelf.sessions.store import SecretsStore, SessionState, SessionUnreadable

STATES = ("not_connected", "checking", "connected", "needs_reconnect")


def _domain_match(host: str, cookie_domain: str) -> bool:
    if cookie_domain.startswith("."):
        base = cookie_domain[1:]
        return host == base or host.endswith("." + base)
    return host == cookie_domain


def _path_match(path: str, cookie_path: str) -> bool:
    path = path or "/"
    if path == cookie_path:
        return True
    if path.startswith(cookie_path):
        return cookie_path.endswith("/") or path[len(cookie_path)] == "/"
    return False


def cookie_header_from_state(session: SessionState, auth: Auth | None, *, capability: str, recipe_auth: str,
                             url: str) -> str | None:
    """Scoped Cookie header for one request, computed from a session state (no connection-state checks)."""
    if auth is None or recipe_auth == "none":
        return None
    if capability not in set(auth.required_for) | set(auth.optional_for):
        return None
    parts = urlsplit(url)
    try:
        host = to_ascii_host(parts.hostname or "")
    except ValueError:
        return None
    if not host_allowed(host, auth.session_domains):
        return None
    now = time.time()
    pairs = []
    for cookie in session.storage_state.get("cookies", []):
        expires = cookie.get("expires", -1)
        if expires not in (-1, None) and expires <= now:
            continue
        if cookie.get("secure") and parts.scheme != "https":
            continue
        if not _domain_match(host, str(cookie.get("domain", "")).lower()):
            continue
        if not _path_match(parts.path, cookie.get("path") or "/"):
            continue
        pairs.append(f"{cookie['name']}={cookie['value']}")
    return "; ".join(pairs) or None


def _origin_allowed(origin: str, auth: Auth) -> bool:
    host = urlsplit(origin).hostname or ""
    try:
        return host_allowed(to_ascii_host(host), auth.session_domains)
    except ValueError:
        return False


def scope_to_session_domains(session: SessionState, auth: Auth) -> SessionState:
    """Least privilege: keep only cookies and origin storage belonging to declared session domains."""
    cookies = [c for c in session.storage_state.get("cookies", [])
               if host_allowed(str(c.get("domain", "")).lstrip(".").lower(), auth.session_domains)]
    origins = [o for o in session.storage_state.get("origins", []) if _origin_allowed(o.get("origin", ""), auth)]
    session_storage = {k: v for k, v in session.session_storage.items() if _origin_allowed(k, auth) and v}
    return SessionState(storage_state={"cookies": cookies, "origins": origins}, session_storage=session_storage)


class SessionManager:
    def __init__(self, conn: sqlite3.Connection, store: SecretsStore, *, events: EventBus | None) -> None:
        self.conn = conn
        self.store = store
        self.events = events
        self._waiters: dict[str, list[asyncio.Future]] = defaultdict(list)

    # -- state ------------------------------------------------------------------------------------

    def state(self, source_id: str) -> str:
        row = self.conn.execute("SELECT state FROM source_session_refs WHERE source_id = ?", (source_id,)).fetchone()
        return row[0] if row else "not_connected"

    def _set_state(self, source_id: str, state: str, reason: str | None = None) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO source_session_refs (source_id, state, secret_ref, updated_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(source_id) DO UPDATE SET state=excluded.state, secret_ref=excluded.secret_ref,"
                " updated_at=excluded.updated_at",
                (source_id, state, f"secrets.db:{source_id}" if state != "not_connected" else None, utcnow_iso()),
            )
        if self.events is not None:
            payload = {"source_id": source_id, "state": state}
            if reason:
                payload["reason"] = reason
            self.events.publish("source.session", payload)
        if state == "connected":
            for future in self._waiters.pop(source_id, []):
                if not future.done():
                    future.set_result(None)

    def connect(self, source_id: str, session: SessionState) -> None:
        """Atomically replace the stored session after a successful login."""
        self.store.put(source_id, session)
        self._set_state(source_id, "connected")

    def confirm_connected(self, source_id: str) -> None:
        """Validation succeeded (or could not be performed) for the stored session."""
        self._set_state(source_id, "connected")

    def mark_checking(self, source_id: str) -> None:
        self._set_state(source_id, "checking")

    def mark_needs_reconnect(self, source_id: str, reason: str) -> None:
        self._set_state(source_id, "needs_reconnect", reason)

    def disconnect(self, source_id: str) -> None:
        self.store.delete(source_id)
        self._set_state(source_id, "not_connected")

    async def wait_until_connected(self, source_id: str) -> None:
        if self.state(source_id) == "connected":
            return
        future = asyncio.get_running_loop().create_future()
        self._waiters[source_id].append(future)
        await future

    # -- scoping ----------------------------------------------------------------------------------

    def _load(self, source_id: str) -> SessionState | None:
        try:
            return self.store.get(source_id)
        except SessionUnreadable:
            if self.state(source_id) != "needs_reconnect":
                self.mark_needs_reconnect(source_id, "stored session could not be read")
            return None

    def cookie_header(self, source_id: str, auth: Auth | None, *, capability: str, recipe_auth: str, url: str) -> str | None:
        if auth is None or recipe_auth == "none" or capability not in set(auth.required_for) | set(auth.optional_for):
            return None
        if self.state(source_id) != "connected":
            return None
        try:
            host = to_ascii_host(urlsplit(url).hostname or "")
        except ValueError:
            return None
        if not host_allowed(host, auth.session_domains):
            return None
        session = self._load(source_id)
        if session is None:
            return None
        return cookie_header_from_state(session, auth, capability=capability, recipe_auth=recipe_auth, url=url)

    def browser_state(self, source_id: str, auth: Auth | None, *, capability: str, recipe_auth: str) -> SessionState | None:
        """Scoped storage state for a browser context, only when this capability may use the session."""
        if auth is None or recipe_auth == "none" or capability not in set(auth.required_for) | set(auth.optional_for):
            return None
        if self.state(source_id) != "connected":
            return None
        session = self._load(source_id)
        return scope_to_session_domains(session, auth) if session is not None else None

    def stored_state(self, source_id: str) -> SessionState | None:
        """Existing session (if readable) so a reconnect can reuse it."""
        return self._load(source_id)

    def refresh_cookies(self, source_id: str, auth: Auth | None, *, url: str, set_cookie_headers: list[str]) -> None:
        """Merge normal cookie refreshes from session-domain responses into the stored session."""
        if auth is None or self.state(source_id) != "connected" or not set_cookie_headers:
            return
        parts = urlsplit(url)
        host = to_ascii_host(parts.hostname or "")
        if not host_allowed(host, auth.session_domains):
            return
        session = self._load(source_id)
        if session is None:
            return
        cookies = {(c["name"], c.get("domain"), c.get("path", "/")): c for c in session.storage_state.get("cookies", [])}
        changed = False
        for header in set_cookie_headers:
            parsed = _parse_set_cookie(header, host)
            if parsed is None:
                continue
            key = (parsed["name"], parsed["domain"], parsed["path"])
            if parsed.pop("_delete", False):
                changed |= cookies.pop(key, None) is not None
            else:
                cookies[key] = parsed
                changed = True
        if changed:
            session.storage_state["cookies"] = list(cookies.values())
            self.store.put(source_id, session)


def _parse_set_cookie(header: str, host: str) -> dict | None:
    pieces = [p.strip() for p in header.split(";")]
    if not pieces or "=" not in pieces[0]:
        return None
    name, value = (x.strip() for x in pieces[0].split("=", 1))
    if not name:
        return None
    cookie = {"name": name, "value": value, "domain": host, "path": "/", "secure": False, "httpOnly": False,
              "expires": -1, "sameSite": "Lax"}
    delete = False
    for attr in pieces[1:]:
        key, _, val = attr.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if key == "domain" and val:
            domain = val.lstrip(".").lower()
            if not (host == domain or host.endswith("." + domain)):
                return None  # a response may not set cookies for unrelated domains
            cookie["domain"] = "." + domain
        elif key == "path" and val.startswith("/"):
            cookie["path"] = val
        elif key == "secure":
            cookie["secure"] = True
        elif key == "httponly":
            cookie["httpOnly"] = True
        elif key == "samesite" and val:
            cookie["sameSite"] = val.capitalize()
        elif key == "max-age" and val.lstrip("-").isdigit():
            if int(val) <= 0:
                delete = True
            else:
                cookie["expires"] = time.time() + int(val)
        elif key == "expires" and val:
            try:
                expires = parsedate_to_datetime(val).timestamp()
            except (TypeError, ValueError):
                continue
            if expires <= time.time():
                delete = True
            cookie["expires"] = expires
    cookie["_delete"] = delete
    return cookie
