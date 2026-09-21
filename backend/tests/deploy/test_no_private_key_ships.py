"""The Registry's private signing key never reaches Git, the build context, or the image.

Only the public Ed25519 key is ever configured. These scan what is actually tracked and what Docker would
actually send, so a key dropped into the tree by mistake fails here before it can be pushed or built.
"""
import subprocess

import pytest

from .test_image_contains_bundled_sources import REPO, dockerignore_rules, excluded

# Assembled rather than written out, so this file does not match its own scan.
_DASHES = b"-" * 5
PRIVATE_KEY_MARKERS = tuple(_DASHES + b"BEGIN " + kind + b"PRIVATE KEY" + _DASHES
                            for kind in (b"", b"OPENSSH ", b"ENCRYPTED ", b"EC ", b"RSA "))


def tracked_files():
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [name for name in listed.decode().split("\0") if name]


def test_no_tracked_file_holds_a_private_key():
    offenders = []
    for name in tracked_files():
        path = REPO / name
        if path.is_file() and any(marker in path.read_bytes() for marker in PRIVATE_KEY_MARKERS):
            offenders.append(name)
    assert offenders == []


def test_no_key_file_is_tracked():
    assert [n for n in tracked_files() if n.endswith((".pem", ".key", ".p8"))] == []


@pytest.mark.parametrize("path", ["registry-signing.pem", "backend/official.key", "deploy/owner.p8",
                                  "backend/plugins/keys/registry.pem"])
def test_the_build_context_leaves_key_files_out(path):
    assert excluded(path, dockerignore_rules())


@pytest.mark.parametrize("path", ["registry-signing.pem", "backend/official.key", "keys/owner.p8"])
def test_git_ignores_key_files(path):
    result = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", path])
    assert result.returncode == 0
