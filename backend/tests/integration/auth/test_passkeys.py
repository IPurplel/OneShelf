"""Master §28.3–28.5: passkey ceremonies on the canonical hostname with a fixed internal identity."""
import pytest

from oneshelf.auth.passkeys import PasskeyError, PasskeyService
from tests.fixtures.authenticator import SoftAuthenticator

RP_ID = "oneshelf.example.net"
ORIGIN = f"https://{RP_ID}"


@pytest.fixture
def passkeys(db):
    return PasskeyService(db, rp_id=RP_ID, origin=ORIGIN)


@pytest.fixture
def authenticator():
    return SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)


def register(passkeys, authenticator, *, label="Phone", authorized_by="lan"):
    ceremony = passkeys.registration_options(authorized_by=authorized_by)
    response = authenticator.register(ceremony.challenge)
    return passkeys.verify_registration(ceremony.id, response, label=label)


def test_register_then_authenticate_a_passkey(db, passkeys, authenticator):
    credential = register(passkeys, authenticator)
    assert credential.label == "Phone" and credential.credential_id
    stored = db.execute("SELECT * FROM remote_credentials").fetchone()
    assert stored["public_key"] and stored["label"] == "Phone"

    ceremony = passkeys.authentication_options()
    verified = passkeys.verify_authentication(ceremony.id, authenticator.authenticate(ceremony.challenge))
    assert verified.credential_id == credential.credential_id
    assert db.execute("SELECT sign_count, last_used_at FROM remote_credentials").fetchone()["sign_count"] == 1


def test_options_name_the_canonical_hostname_and_never_expose_an_account(passkeys):
    options = passkeys.registration_options(authorized_by="lan").options
    assert options["rp"]["id"] == RP_ID and options["rp"]["name"] == "OneShelf"
    assert options["user"]["name"] == "oneshelf" and options["user"]["displayName"] == "OneShelf"
    assert options["authenticatorSelection"]["residentKey"] == "required"


def test_a_challenge_works_once(passkeys, authenticator):
    register(passkeys, authenticator)
    ceremony = passkeys.authentication_options()
    response = authenticator.authenticate(ceremony.challenge)
    passkeys.verify_authentication(ceremony.id, response)
    with pytest.raises(PasskeyError):
        passkeys.verify_authentication(ceremony.id, response)


def test_expired_challenges_are_refused(db, passkeys, authenticator):
    ceremony = passkeys.registration_options(authorized_by="lan")
    db.execute("UPDATE webauthn_challenges SET expires_at = '2000-01-01T00:00:00+00:00'")
    with pytest.raises(PasskeyError):
        passkeys.verify_registration(ceremony.id, authenticator.register(ceremony.challenge), label="Phone")


def test_a_response_for_another_origin_or_hostname_is_refused(passkeys, authenticator):
    ceremony = passkeys.registration_options(authorized_by="lan")
    with pytest.raises(PasskeyError):
        passkeys.verify_registration(ceremony.id, authenticator.register(ceremony.challenge,
                                                                        origin="https://evil.example"), label="Phone")
    ceremony = passkeys.registration_options(authorized_by="lan")
    with pytest.raises(PasskeyError):
        passkeys.verify_registration(ceremony.id, authenticator.register(ceremony.challenge, rp_id="evil.example"),
                                     label="Phone")


def test_an_unknown_credential_cannot_authenticate(passkeys, authenticator):
    register(passkeys, authenticator)
    stranger = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    ceremony = passkeys.authentication_options()
    with pytest.raises(PasskeyError):
        passkeys.verify_authentication(ceremony.id, stranger.authenticate(ceremony.challenge))


def test_a_cloned_authenticator_is_detected_by_the_sign_counter(passkeys, authenticator):
    register(passkeys, authenticator)
    first = passkeys.authentication_options()
    passkeys.verify_authentication(first.id, authenticator.authenticate(first.challenge))
    second = passkeys.authentication_options()
    with pytest.raises(PasskeyError):
        passkeys.verify_authentication(second.id, authenticator.authenticate(second.challenge, sign_count=1))


def test_registration_requires_an_authorization_and_credentials_can_be_listed_and_removed(passkeys, authenticator):
    with pytest.raises(PasskeyError):
        passkeys.registration_options(authorized_by="nothing")
    credential = register(passkeys, authenticator, label="Laptop")
    assert [c.label for c in passkeys.list_credentials()] == ["Laptop"]
    assert passkeys.delete_credential(credential.credential_id) is True
    assert passkeys.list_credentials() == []
