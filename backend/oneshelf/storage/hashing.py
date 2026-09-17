import hashlib
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_file(path: str | Path) -> tuple[str, int]:
    """Streamed SHA-256 and size; never loads the whole file into memory."""
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
