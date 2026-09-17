"""Short stable OneShelf IDs: lowercase base32, filename-safe (Master §24.2)."""
import base64
import secrets

ID_LENGTH = 12  # 60 bits of randomness


def new_id() -> str:
    raw = base64.b32encode(secrets.token_bytes(8)).decode("ascii").lower()
    return raw[:ID_LENGTH]
