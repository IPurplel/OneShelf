"""Master §28.6: remote UI sessions — labels, lifetimes, revocation and cookie safety."""
from datetime import UTC, datetime, timedelta

import pytest

from oneshelf.auth.sessions import LIFETIMES, RemoteSessions, SessionError, cookie_attributes


@pytest.fixture
def clock():
    return {"now": datetime(2026, 9, 17, 12, 0, tzinfo=UTC)}


@pytest.fixture
def sessions(db, clock):
    return RemoteSessions(db, clock=lambda: clock["now"])


def test_token_is_returned_once_and_never_stored(db, sessions):
    issued = sessions.create(label="Firefox on Linux")
    stored = db.execute("SELECT * FROM remote_sessions WHERE id = ?", (issued.session_id,)).fetchone()
    assert issued.token and issued.token not in dict(stored).values()
    assert stored["token_hash"] != issued.token and len(stored["token_hash"]) == 64


def test_validating_a_session_records_activity(sessions, clock):
    issued = sessions.create(label="iPhone")
    clock["now"] += timedelta(hours=5)
    session = sessions.validate(issued.token)
    assert session.id == issued.session_id and session.label == "iPhone"
    assert session.last_active_at == clock["now"].isoformat()
    assert sessions.validate("not-a-real-token") is None


def test_default_lifetime_is_thirty_days(sessions, clock):
    issued = sessions.create(label="Laptop")
    assert issued.expires_at == (clock["now"] + timedelta(days=30)).isoformat()
    clock["now"] += timedelta(days=30, seconds=1)
    assert sessions.validate(issued.token) is None


@pytest.mark.parametrize("lifetime,days", [("7d", 7), ("30d", 30), ("90d", 90), ("1y", 365)])
def test_configurable_lifetimes(sessions, clock, lifetime, days):
    issued = sessions.create(label="Tablet", lifetime=lifetime)
    assert issued.expires_at == (clock["now"] + timedelta(days=days)).isoformat()
    assert set(LIFETIMES) == {"7d", "30d", "90d", "1y", "manual"}


def test_manual_lifetime_never_expires_on_its_own(sessions, clock):
    issued = sessions.create(label="Home server", lifetime="manual")
    assert issued.expires_at is None
    clock["now"] += timedelta(days=4000)
    assert sessions.validate(issued.token) is not None
    with pytest.raises(SessionError):
        sessions.create(label="Bad", lifetime="forever")


def test_listing_marks_the_current_session_without_fingerprinting(sessions):
    first = sessions.create(label="Firefox on Linux")
    second = sessions.create(label="iPhone")
    listed = sessions.list_sessions(current_token=second.token)
    assert {s.label: s.current for s in listed} == {"Firefox on Linux": False, "iPhone": True}
    assert not any(hasattr(s, "user_agent") or hasattr(s, "fingerprint") for s in listed)
    assert all(s.created_at and s.last_active_at for s in listed)


def test_revoke_and_revoke_all_other_sessions(sessions):
    keep = sessions.create(label="Current")
    other = sessions.create(label="Other")
    third = sessions.create(label="Old tablet")

    sessions.revoke(other.session_id)
    assert sessions.validate(other.token) is None
    assert sessions.validate(third.token) is not None

    assert sessions.revoke_others(current_token=keep.token) == 1
    assert sessions.validate(third.token) is None
    assert sessions.validate(keep.token) is not None
    assert [s.label for s in sessions.list_sessions()] == ["Current"]


def test_cookies_are_httponly_samesite_and_secure_only_on_https():
    https = cookie_attributes(secure=True)
    assert https["httponly"] is True and https["secure"] is True and https["samesite"] == "lax"
    assert cookie_attributes(secure=False)["secure"] is False    # plain-HTTP LAN access still works
