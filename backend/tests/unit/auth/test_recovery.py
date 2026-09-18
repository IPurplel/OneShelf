"""Master §28.5: the Recovery Code is a verifier-only credential that authorizes a new passkey."""
import pytest

from oneshelf.auth.recovery import RecoveryCodes


@pytest.fixture
def recovery(db):
    return RecoveryCodes(db)


def test_generated_code_is_readable_and_stored_only_as_a_verifier(db, recovery):
    code = recovery.generate()
    assert len(code.replace("-", "")) >= 20 and code.count("-") >= 3
    row = db.execute("SELECT * FROM remote_recovery").fetchone()
    assert code not in dict(row).values() and row["verifier"] != code and row["salt"]
    assert recovery.status()["created_at"] == row["created_at"]


def test_verify_accepts_the_code_and_rejects_anything_else(recovery):
    code = recovery.generate()
    assert recovery.verify(code) is True
    assert recovery.verify(code.lower().replace("-", " ")) is True     # forgiving about case and spacing
    assert recovery.verify("WRONG-CODE-0000-0000") is False
    assert recovery.verify("") is False


def test_regeneration_invalidates_the_previous_code(recovery):
    first = recovery.generate()
    second = recovery.generate()
    assert first != second
    assert recovery.verify(first) is False and recovery.verify(second) is True


def test_no_code_exists_before_the_first_passkey(recovery):
    assert recovery.status()["configured"] is False
    assert recovery.verify("ANY-CODE-HERE-1234") is False
    recovery.generate()
    assert recovery.status()["configured"] is True
