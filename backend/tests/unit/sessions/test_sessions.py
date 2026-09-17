"""Master §13: Core-owned, encrypted, source-isolated, capability/domain-scoped source sessions."""
import asyncio
import os
import sqlite3
import stat
import time
from contextlib import closing

import pytest

from oneshelf.events.bus import EventBus
from oneshelf.plugins.schema import Auth
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, SessionState, SessionUnreadable, load_or_create_key

SECRET = "sid-SUPER-SECRET-value-123"
AUTH = Auth(login_url="https://books.example/login", session_domains=["books.example"],
            required_for=["catalog"], optional_for=["search"])


def state(value=SECRET, domain="books.example", **cookie):
    c = {"name": "sid", "value": value, "domain": domain, "path": "/", "secure": True, "httpOnly": True,
         "expires": -1, "sameSite": "Lax"} | cookie
    return SessionState(storage_state={"cookies": [c], "origins": [
        {"origin": "https://books.example", "localStorage": [{"name": "token", "value": "LS-" + value}]}]},
        session_storage={"https://books.example": {"tab": "SS-" + value}})


@pytest.fixture
def paths(tmp_path):
    return {"key": tmp_path / "keys" / "session.key", "secrets": tmp_path / "app" / "secrets.db"}


@pytest.fixture
def store(paths):
    s = SecretsStore(paths["secrets"], load_or_create_key(paths["key"]))
    yield s
    s.close()


@pytest.fixture
def manager(db, store):
    return SessionManager(db, store, events=None)


def test_key_file_is_private_and_stable(paths):
    key = load_or_create_key(paths["key"])
    assert len(key) == 32
    assert stat.S_IMODE(os.stat(paths["key"]).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(paths["key"].parent).st_mode) == 0o700
    assert load_or_create_key(paths["key"]) == key


def test_secrets_are_encrypted_at_rest(store, paths):
    store.put("example.books", state())
    raw = paths["secrets"].read_bytes()
    assert SECRET.encode() not in raw and b"LS-" not in raw and b"SS-" not in raw
    assert store.get("example.books").storage_state["cookies"][0]["value"] == SECRET


def test_ciphertext_is_bound_to_its_source(store, paths):
    store.put("source.a", state("A-secret"))
    store.put("source.b", state("B-secret"))
    with closing(sqlite3.connect(paths["secrets"])) as c:
        a = c.execute("SELECT nonce, ciphertext FROM source_sessions WHERE source_id='source.a'").fetchone()
        c.execute("UPDATE source_sessions SET nonce=?, ciphertext=? WHERE source_id='source.b'", a)
        c.commit()
    with pytest.raises(SessionUnreadable):
        store.get("source.b")


def test_wrong_key_makes_sessions_unreadable_not_crashing(paths):
    s1 = SecretsStore(paths["secrets"], load_or_create_key(paths["key"]))
    s1.put("example.books", state())
    s1.close()
    s2 = SecretsStore(paths["secrets"], os.urandom(32))
    with pytest.raises(SessionUnreadable):
        s2.get("example.books")
    s2.close()


def test_disconnect_deletes_session_bytes(store, paths):
    store.put("example.books", state())
    with closing(sqlite3.connect(paths["secrets"])) as c:
        ciphertext = c.execute("SELECT ciphertext FROM source_sessions").fetchone()[0]
    store.delete("example.books")
    assert store.get("example.books") is None
    assert ciphertext[:32] not in paths["secrets"].read_bytes()  # secure_delete zeroed the freed page


def test_session_state_repr_is_redacted():
    text = repr(state()) + str(state())
    assert SECRET not in text and "LS-" not in text and "redacted" in text


def test_connect_disconnect_state_transitions_and_events(db, store):
    bus = EventBus()
    events = []

    async def scenario():
        sub = bus.subscribe()
        m = SessionManager(db, store, events=bus)
        assert m.state("example.books") == "not_connected"
        m.connect("example.books", state())
        assert m.state("example.books") == "connected"
        m.mark_needs_reconnect("example.books", "HTTP 401")
        assert m.state("example.books") == "needs_reconnect"
        assert store.get("example.books") is not None  # old state kept for reuse
        m.disconnect("example.books")
        assert m.state("example.books") == "not_connected" and store.get("example.books") is None
        while not sub.queue.empty():
            events.append(await sub.get())

    asyncio.run(scenario())
    assert [e.data["state"] for e in events] == ["connected", "needs_reconnect", "not_connected"]
    assert all(SECRET not in repr(e.data) for e in events)


def test_reconnect_replaces_atomically_and_resumes_waiters(db, store):
    async def scenario():
        m = SessionManager(db, store, events=None)
        m.connect("example.books", state("old"))
        m.mark_needs_reconnect("example.books", "expired")
        waiter = asyncio.create_task(m.wait_until_connected("example.books"))
        await asyncio.sleep(0.01)
        assert not waiter.done()
        m.connect("example.books", state("new"))
        await asyncio.wait_for(waiter, 1)
        return m.cookie_header("example.books", AUTH, capability="catalog", recipe_auth="required",
                               url="https://books.example/api/x")
    assert asyncio.run(scenario()) == "sid=new"


def test_unreadable_session_is_reported_as_needs_reconnect(db, paths):
    s1 = SecretsStore(paths["secrets"], load_or_create_key(paths["key"]))
    SessionManager(db, s1, events=None).connect("example.books", state())
    s1.close()
    s2 = SecretsStore(paths["secrets"], os.urandom(32))
    m = SessionManager(db, s2, events=None)
    assert m.cookie_header("example.books", AUTH, capability="catalog", recipe_auth="required",
                           url="https://books.example/x") is None
    assert m.state("example.books") == "needs_reconnect"
    s2.close()


@pytest.mark.parametrize("kwargs,expected", [
    ({"capability": "catalog", "recipe_auth": "required", "url": "https://books.example/api/x"}, "sid=" + SECRET),
    ({"capability": "search", "recipe_auth": "optional", "url": "https://books.example/s"}, "sid=" + SECRET),
    ({"capability": "catalog", "recipe_auth": "none", "url": "https://books.example/api/x"}, None),
    ({"capability": "reader", "recipe_auth": "required", "url": "https://books.example/r"}, None),  # not in manifest auth
    ({"capability": "catalog", "recipe_auth": "required", "url": "https://img.cdn.books.example/p.jpg"}, None),  # CDN
    ({"capability": "catalog", "recipe_auth": "required", "url": "https://evil.example/x"}, None),
    ({"capability": "catalog", "recipe_auth": "required", "url": "http://books.example/x"}, None),  # secure cookie
])
def test_cookie_scoping(manager, kwargs, expected):
    manager.connect("example.books", state())
    assert manager.cookie_header("example.books", AUTH, **kwargs) == expected


def test_sessions_are_isolated_between_sources(manager):
    manager.connect("example.books", state("books-secret"))
    other_auth = Auth(login_url="https://comics.example/login", session_domains=["comics.example"], required_for=["catalog"])
    assert manager.cookie_header("other.comics", other_auth, capability="catalog", recipe_auth="required",
                                 url="https://comics.example/x") is None
    assert manager.cookie_header("other.comics", AUTH, capability="catalog", recipe_auth="required",
                                 url="https://books.example/x") is None


@pytest.mark.parametrize("cookie,url,sent", [
    ({"domain": ".books.example"}, "https://www.books.example/x", False),  # www not in session_domains
    ({"domain": "books.example", "path": "/api"}, "https://books.example/api/v1", True),
    ({"domain": "books.example", "path": "/api"}, "https://books.example/apiary", False),
    ({"domain": "books.example", "expires": time.time() - 10}, "https://books.example/x", False),
    ({"domain": "other.example"}, "https://books.example/x", False),
])
def test_cookie_attribute_matching(manager, cookie, url, sent):
    manager.connect("example.books", state(**cookie))
    header = manager.cookie_header("example.books", AUTH, capability="catalog", recipe_auth="required", url=url)
    assert (header is not None) is sent


def test_refreshed_cookies_update_only_session_domains(manager, store):
    manager.connect("example.books", state("v1"))
    manager.refresh_cookies("example.books", AUTH, url="https://books.example/api",
                            set_cookie_headers=["sid=v2; Path=/; Secure; HttpOnly", "tracker=1; Domain=evil.example"])
    cookies = {c["name"]: c for c in store.get("example.books").storage_state["cookies"]}
    assert cookies["sid"]["value"] == "v2" and "tracker" not in cookies
    manager.refresh_cookies("example.books", AUTH, url="https://img.cdn.books.example/p.jpg",
                            set_cookie_headers=["sid=cdn-injected; Domain=books.example"])
    assert {c["name"]: c for c in store.get("example.books").storage_state["cookies"]}["sid"]["value"] == "v2"
