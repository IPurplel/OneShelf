"""Core-owned filesystem safety (Master §24.2, §24.4, §48).

Plugins, source metadata and imported filenames are untrusted. Only this module turns names into
path components, and every managed path is resolved through resolve_within().
"""
from __future__ import annotations

import os
import re
import stat
import unicodedata
from pathlib import Path, PurePosixPath

DEFAULT_COMPONENT_BYTES = 150
_KEEP_FORMAT_CHARS = {"‌", "‍"}  # ZWNJ / ZWJ are meaningful in Arabic and other scripts
_RESERVED_CHARS = re.compile(r'[<>:"|?*/\\]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_DRIVE = re.compile(r"^[A-Za-z]:")


class PathSafetyError(ValueError):
    pass


def safe_component(name: str, *, max_bytes: int = DEFAULT_COMPONENT_BYTES) -> str:
    text = unicodedata.normalize("NFC", name)
    text = "".join(
        ch
        for ch in text
        if ch in _KEEP_FORMAT_CHARS or unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    )
    text = _RESERVED_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    encoded = text.encode("utf-8")[:max_bytes]
    text = encoded.decode("utf-8", errors="ignore").strip(" .")
    if not text:
        return "untitled"
    stem, dot, suffix = text.partition(".")
    if stem.upper() in _WINDOWS_RESERVED:
        text = f"{stem}_{dot}{suffix}"
    return text


def _check_relative(relative: str) -> list[str]:
    if not relative or "\x00" in relative or "\\" in relative:
        raise PathSafetyError(f"unsafe managed path: {relative!r}")
    if PurePosixPath(relative).is_absolute() or _DRIVE.match(relative):
        raise PathSafetyError(f"absolute path not allowed: {relative!r}")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PathSafetyError(f"path traversal or empty segment: {relative!r}")
    return parts


def resolve_within(root: str | Path, relative: str) -> Path:
    """Join a managed relative path onto a root, refusing traversal and any symlink below the root."""
    root = Path(root)
    parts = _check_relative(relative)
    current = root
    for part in parts:
        current = current / part
        if os.path.islink(current):
            raise PathSafetyError(f"symlink inside managed root: {relative!r}")
    root_real = os.path.realpath(root)
    if os.path.commonpath([root_real, os.path.realpath(current)]) != root_real:
        raise PathSafetyError(f"path escapes managed root: {relative!r}")
    return current


def delete_managed_file(root: str | Path, relative: str) -> None:
    target = resolve_within(root, relative)
    mode = os.lstat(target).st_mode
    if not stat.S_ISREG(mode):
        raise PathSafetyError(f"refusing to delete non-regular file: {relative!r}")
    os.unlink(target)
