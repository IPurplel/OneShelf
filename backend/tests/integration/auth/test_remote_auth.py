"""Master §28.1–28.6: remote auth lifecycle, recovery, and the strict scope of LAN Recovery."""
import pytest

from oneshelf.auth.passkeys import PasskeyError
from oneshelf.auth.service import RemoteAuth, RemoteAuthError
from tests.fixtures.authenticator import SoftAuthenticator

RP_ID = "oneshelf.example.net"


@pytest.fixture
def auth(db):
    service = RemoteAuth(db)
    service.set_canonical_hostname(RP_ID)
    return service


@pytest.fixture
def authenticator():
    return SoftAuthenticator(rp_id=RP_ID, origin=f"https://{RP_ID}")


def enrol(auth, authenticator, *, access="lan", label="Phone", **kwargs):
    ceremony = auth.begin_registration(access=access, label=label, **kwargs)
    return auth.complete_registration(ceremony.id, authenticator.register(ceremony.challenge), label=label)


def sign_in(auth, authenticator, **kwargs):
    ceremony = auth.begin_authentication()
    return auth.complete_authentication(ceremony.id, authenticator.authenticate(ceremony.challenge), **kwargs)


def library_fingerprint(db):
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("works", "shelf_entries", "reading_state", "download_jobs", "plugins", "source_session_refs",
                      "assets", "follows")}


def test_first_passkey_comes_with_a_recovery_code_shown_once(auth, authenticator):
    outcome = enrol(auth, authenticator)
    assert outcome.credential.label == "Phone"
    assert outcome.recovery_code and len(outcome.recovery_code.replace("-", "")) >= 20
    assert auth.state()["recovery"]["configured"] is True

    second = SoftAuthenticator(rp_id=RP_ID, origin=f"https://{RP_ID}")
    again = enrol(auth, second, label="Tablet")
    assert again.recovery_code is None      # only the first setup issues one; regeneration is explicit


def test_remote_sign_in_issues_a_session_with_the_configured_lifetime(auth, authenticator):
    enrol(auth, authenticator)
    issued = sign_in(auth, authenticator, label="Firefox on Linux", lifetime="90d")
    assert issued.token and issued.expires_at
    assert [s.label for s in auth.sessions.list_sessions()] == ["Firefox on Linux"]
    assert auth.sessions.validate(issued.token) is not None


def test_a_remote_client_cannot_register_a_passkey_on_its_own(auth, authenticator):
    with pytest.raises(RemoteAuthError):
        auth.begin_registration(access="remote", label="Attacker")
    with pytest.raises(RemoteAuthError):
        auth.begin_registration(access="remote", label="Attacker", recovery_code="WRONG-CODE-HERE-0000")


def test_a_recovery_code_authorizes_a_new_passkey_and_regeneration_invalidates_it(auth, authenticator):
    code = enrol(auth, authenticator).recovery_code
    replacement = SoftAuthenticator(rp_id=RP_ID, origin=f"https://{RP_ID}")
    enrol(auth, replacement, access="remote", label="New phone", recovery_code=code)
    assert {c.label for c in auth.passkeys.list_credentials()} == {"Phone", "New phone"}
    assert auth.state()["recovery"]["last_used_at"] is not None

    fresh = auth.regenerate_recovery_code()
    assert fresh != code
    with pytest.raises(RemoteAuthError):
        auth.begin_registration(access="remote", label="Too late", recovery_code=code)


def test_lan_recovery_resets_remote_auth_only(db, auth, authenticator):
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at)"
               " VALUES ('w1','Solo Leveling','manga','2026-09-17T12:00:00+00:00','2026-09-17T12:00:00+00:00')")
    db.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES ('w1','2026-09-17T12:00:00+00:00')")
    db.execute("INSERT INTO source_session_refs (source_id, state, secret_ref, updated_at)"
               " VALUES ('mangadex','connected','secrets.db:mangadex','2026-09-17T12:00:00+00:00')")
    enrol(auth, authenticator)
    issued = sign_in(auth, authenticator, label="Old phone")
    before = library_fingerprint(db)

    report = auth.lan_recovery_reset(access="lan")
    assert report.passkeys_removed == 1 and report.sessions_revoked == 1
    assert "remote web ui" in report.message.lower() and "library" in report.message.lower()
    assert auth.passkeys.list_credentials() == [] and auth.sessions.list_sessions() == []
    assert auth.sessions.validate(issued.token) is None
    assert library_fingerprint(db) == before        # §28.5: nothing but remote auth is touched
    assert auth.state()["passkeys"] == [] and auth.state()["recovery"]["configured"] is False

    # a new passkey can be registered again straight from the LAN
    fresh = SoftAuthenticator(rp_id=RP_ID, origin=f"https://{RP_ID}")
    assert enrol(auth, fresh, label="Replacement").recovery_code is not None


def test_lan_recovery_is_refused_from_anywhere_but_a_genuine_lan_or_loopback(auth, authenticator):
    enrol(auth, authenticator)
    for access in ("remote",):
        with pytest.raises(RemoteAuthError):
            auth.lan_recovery_reset(access=access)
    assert auth.passkeys.list_credentials() != []


def test_remote_access_needs_a_canonical_hostname(db, authenticator):
    service = RemoteAuth(db)
    assert service.state()["canonical_hostname"] is None
    with pytest.raises(RemoteAuthError):
        service.begin_registration(access="lan", label="Phone")
    service.set_canonical_hostname("https://oneshelf.example.net/")
    assert service.state()["canonical_hostname"] == RP_ID       # stored as the bare host, never a URL
    with pytest.raises(RemoteAuthError):
        service.set_canonical_hostname("not a hostname")


def test_signing_out_revokes_only_that_session(auth, authenticator):
    enrol(auth, authenticator)
    first = sign_in(auth, authenticator, label="Phone")
    second = sign_in(auth, authenticator, label="Laptop")
    auth.sign_out(first.token)
    assert auth.sessions.validate(first.token) is None
    assert auth.sessions.validate(second.token) is not None


def test_authentication_without_a_passkey_is_refused(auth):
    with pytest.raises(PasskeyError):
        auth.begin_authentication()
