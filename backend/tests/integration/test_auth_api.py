"""Master §28–§29 over HTTP: remote passkey sign-in, LAN trust, sessions, recovery and First Run."""
import base64

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.auth.sessions import COOKIE_NAME
from tests.fixtures.authenticator import SoftAuthenticator

HOSTNAME = "oneshelf.example.net"
LAN_PEER = ("192.168.1.10", 51000)
REMOTE_PEER = ("203.0.113.9", 51000)


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@pytest.fixture
def app(tmp_path):
    return create_app(AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"),
        "ONESHELF_ALLOWED_HOSTS": f"testserver,{HOSTNAME}",
        "ONESHELF_TRUSTED_NETWORKS": "192.168.1.0/24",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
    }))


@pytest.fixture
def lan(app):
    with TestClient(app, client=LAN_PEER) as client:
        yield client


@pytest.fixture
def remote(app):
    with TestClient(app, client=REMOTE_PEER) as client:
        yield client


@pytest.fixture
def authenticator():
    return SoftAuthenticator(rp_id=HOSTNAME, origin=f"https://{HOSTNAME}")


def enrol(lan, authenticator, label="Phone"):
    lan.post("/api/auth/hostname", json={"hostname": HOSTNAME})
    ceremony = lan.post("/api/auth/passkeys/register/options", json={"label": label}).json()
    response = authenticator.register(unb64(ceremony["options"]["challenge"]))
    return lan.post("/api/auth/passkeys/register",
                    json={"ceremony_id": ceremony["ceremony_id"], "label": label, "response": response}).json()


def sign_in(remote, authenticator, **body):
    ceremony = remote.post("/api/auth/sign-in/options").json()
    response = authenticator.authenticate(unb64(ceremony["options"]["challenge"]))
    return remote.post("/api/auth/sign-in", json={"ceremony_id": ceremony["ceremony_id"], "response": response, **body})


def test_remote_access_is_refused_until_a_passkey_session_exists(remote):
    denied = remote.get("/api/health")
    assert denied.status_code == 401 and denied.json()["error"]["code"] == "REMOTE_AUTH_REQUIRED"
    assert remote.get("/api/auth/state").status_code == 401


def test_lan_is_trusted_and_can_enrol_a_passkey_that_remote_then_uses(lan, remote, authenticator):
    assert lan.get("/api/health").json()["access"] == "lan"
    enrolment = enrol(lan, authenticator)
    assert enrolment["credential"]["label"] == "Phone" and enrolment["recovery_code"]

    response = sign_in(remote, authenticator, label="Firefox on Linux", lifetime="90d")
    assert response.status_code == 200 and response.json()["expires_at"]
    cookie = response.headers["set-cookie"]
    assert COOKIE_NAME in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Secure" not in cookie                       # plain HTTP here; Secure is set on HTTPS
    assert "token" not in response.json()               # the token only ever travels in the cookie

    assert remote.get("/api/health").json()["access"] == "remote"
    assert remote.get("/api/auth/state").json()["passkeys"][0]["label"] == "Phone"


def test_a_remote_client_cannot_enrol_itself_or_forge_lan_trust(remote, authenticator):
    assert remote.post("/api/auth/hostname", json={"hostname": HOSTNAME}).status_code == 401
    forged = remote.get("/api/health", headers={"X-Forwarded-For": "192.168.1.50"})
    assert forged.status_code == 401                    # no trusted proxy is configured (§28.2)


def test_registration_from_a_signed_in_remote_session_is_allowed_but_never_anonymously(lan, remote, authenticator):
    enrol(lan, authenticator)
    sign_in(remote, authenticator)
    second = SoftAuthenticator(rp_id=HOSTNAME, origin=f"https://{HOSTNAME}")
    ceremony = remote.post("/api/auth/passkeys/register/options", json={"label": "Laptop"})
    assert ceremony.status_code == 200
    registered = remote.post("/api/auth/passkeys/register",
                             json={"ceremony_id": ceremony.json()["ceremony_id"], "label": "Laptop",
                                   "response": second.register(unb64(ceremony.json()["options"]["challenge"]))})
    assert registered.status_code == 200 and registered.json()["recovery_code"] is None
    assert {p["label"] for p in lan.get("/api/auth/state").json()["passkeys"]} == {"Phone", "Laptop"}


def test_sessions_can_be_listed_and_revoked(lan, remote, authenticator):
    enrol(lan, authenticator)
    sign_in(remote, authenticator, label="Old tablet")
    listed = lan.get("/api/auth/sessions").json()["sessions"]
    assert [s["label"] for s in listed] == ["Old tablet"] and listed[0]["current"] is False

    assert lan.delete(f"/api/auth/sessions/{listed[0]['id']}").status_code == 200
    assert remote.get("/api/health").status_code == 401

    sign_in(remote, authenticator, label="Phone again")
    assert remote.get("/api/health").status_code == 200
    assert remote.post("/api/auth/sessions/revoke-others").json()["revoked"] == 0
    assert remote.get("/api/health").status_code == 200          # its own session survives


def test_sign_out_only_ends_the_current_session(lan, remote, authenticator):
    enrol(lan, authenticator)
    sign_in(remote, authenticator)
    assert remote.post("/api/auth/sign-out").status_code == 200
    assert remote.get("/api/health").status_code == 401


def test_lan_recovery_resets_remote_auth_and_says_so(lan, remote, authenticator):
    enrol(lan, authenticator)
    sign_in(remote, authenticator)
    refused = remote.post("/api/auth/lan-recovery")     # signed in, but not on the LAN
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "LAN_RECOVERY_UNAVAILABLE"

    report = lan.post("/api/auth/lan-recovery").json()
    assert report["passkeys_removed"] == 1 and report["sessions_revoked"] == 1
    assert "remote web ui" in report["message"].lower()
    assert lan.get("/api/auth/state").json()["passkeys"] == []
    assert remote.get("/api/health").status_code == 401


def test_recovery_code_can_be_regenerated_from_the_lan(lan, authenticator):
    first = enrol(lan, authenticator)["recovery_code"]
    regenerated = lan.post("/api/auth/recovery/regenerate").json()["recovery_code"]
    assert regenerated != first
    assert lan.get("/api/auth/state").json()["recovery"]["configured"] is True


def test_cross_site_requests_are_refused(lan, authenticator):
    enrol(lan, authenticator)
    blocked = lan.post("/api/auth/recovery/regenerate", headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "CROSS_ORIGIN_REQUEST"


def test_first_run_is_short_and_never_blocks_home(lan, tmp_path):
    assert lan.get("/api/health").status_code == 200                  # nothing is gated on first run
    state = lan.get("/api/first-run").json()
    assert state["state"] == "pending" and state["steps"][0]["id"] == "welcome"

    (tmp_path / "library").mkdir()
    storage = lan.post("/api/first-run/storage", json={"name": "Library", "path": str(tmp_path / "library")})
    assert storage.status_code == 200 and storage.json()["default"] is True

    access = lan.post("/api/first-run/access-mode", json={"mode": "lan", "trusted_networks": ["192.168.5.0/24"]})
    assert access.status_code == 200
    assert "192.168.5.0/24" in access.json()["network"]["trusted_networks"]

    finished = lan.post("/api/first-run/finish").json()
    assert finished["state"] == "completed" and finished["access_mode"] == "lan"
    assert lan.get("/api/first-run").json()["state"] == "completed"


def test_first_run_remote_mode_needs_a_hostname_and_a_passkey(lan, authenticator):
    lan.post("/api/first-run/access-mode", json={"mode": "remote", "canonical_hostname": HOSTNAME})
    pending = lan.get("/api/first-run").json()
    assert pending["access_mode"] == "remote" and pending["remote"]["canonical_hostname"] == HOSTNAME
    assert pending["remote"]["passkey_registered"] is False
    assert lan.post("/api/first-run/finish").status_code == 409     # a remote setup without a passkey is useless

    enrol(lan, authenticator)
    assert lan.post("/api/first-run/finish").json()["state"] == "completed"


def test_bad_hostnames_are_rejected(lan):
    assert lan.post("/api/auth/hostname", json={"hostname": "not a hostname"}).status_code == 422
    assert lan.post("/api/auth/hostname", json={"hostname": "https://oneshelf.example.net/"}).json()["hostname"] \
        == HOSTNAME


@pytest.fixture
def proxied(tmp_path):
    """A reverse proxy that sits inside the LAN and forwards internet traffic (Master §28.2)."""
    app = create_app(AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "proxied"),
        "ONESHELF_ALLOWED_HOSTS": f"testserver,{HOSTNAME}",
        "ONESHELF_TRUSTED_NETWORKS": "192.168.1.0/24",
        "ONESHELF_TRUSTED_PROXIES": "192.168.1.5/32",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
    }))
    with TestClient(app, client=("192.168.1.5", 52000)) as client:
        yield client


def test_a_trusted_proxy_never_lends_its_own_lan_trust_to_remote_visitors(proxied):
    assert proxied.get("/api/health").status_code == 401            # the proxy itself is not a LAN device
    remote_visitor = proxied.get("/api/health", headers={"X-Forwarded-For": "203.0.113.9"})
    assert remote_visitor.status_code == 401
    chained = proxied.get("/api/health", headers={"X-Forwarded-For": "203.0.113.9, 192.168.1.5"})
    assert chained.status_code == 401                                # a client cannot prepend its way in
    lan_visitor = proxied.get("/api/health", headers={"X-Forwarded-For": "192.168.1.30"})
    assert lan_visitor.status_code == 200 and lan_visitor.json()["access"] == "lan"


def test_a_lan_client_that_is_not_a_configured_proxy_cannot_forge_a_client_address(lan):
    spoofed = lan.get("/api/health", headers={"X-Forwarded-For": "203.0.113.9"})
    assert spoofed.status_code == 200 and spoofed.json()["access"] == "lan"   # header ignored entirely


def test_the_configured_canonical_hostname_is_accepted_without_extra_configuration(tmp_path):
    """Setting the hostname in First Run is enough; the Host allowlist follows it (ledger D-C3-13)."""
    app = create_app(AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "hosts"),
        "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_TRUSTED_NETWORKS": "192.168.1.0/24",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
    }))
    with TestClient(app, client=LAN_PEER) as client:
        refused = client.get("/api/health", headers={"Host": HOSTNAME})
        assert refused.status_code == 421

        client.post("/api/auth/hostname", json={"hostname": HOSTNAME})
        assert client.get("/api/health", headers={"Host": HOSTNAME}).status_code == 200
        assert client.get("/api/health", headers={"Host": "someone-elses.example"}).status_code == 421
