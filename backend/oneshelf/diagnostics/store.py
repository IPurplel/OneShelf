"""The local diagnostics store (Master §43, DEF-diagnostics).

Operational records only — parser, network, job and health detail — written redacted and kept for at
most seven days or a hundred megabytes, whichever binds first. It never leaves the machine: there is no
endpoint that sends it anywhere, it is excluded from backups by construction (§33.3), and it may not
become a record of matching decisions under another name (§6.10, INV-29).
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime, timedelta, UTC
from pathlib import Path

from oneshelf.diagnostics.redact import RedactingFilter, redact_headers, redact_text, redact_url
from oneshelf.settings.defaults import DEFAULTS

CATEGORIES = ("parser", "network", "job", "health")
_SEGMENT_BYTES = 512 * 1024


def _redact(value):
    """Redaction happens on the way in, so nothing sensitive is ever at rest (§43, §48)."""
    if isinstance(value, dict):
        headers = {k: v for k, v in value.items() if k.lower() in ("headers", "header")}
        out = {}
        for key, item in value.items():
            if key in headers and isinstance(item, dict):
                out[key] = redact_headers(item)
            elif isinstance(item, str) and item.startswith(("http://", "https://")):
                out[key] = redact_url(item)
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class DiagnosticsStore:
    def __init__(self, directory: str | Path, *, clock: Callable[[], datetime] | None = None,
                 max_bytes: int | None = None, max_age: timedelta | None = None) -> None:
        self.directory = Path(directory)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_bytes = max_bytes if max_bytes is not None else DEFAULTS.diagnostics.max_bytes
        self.max_age = max_age if max_age is not None else DEFAULTS.diagnostics.max_age
        self.directory.mkdir(parents=True, exist_ok=True)

    # -- writing -----------------------------------------------------------------------------------

    def record(self, category: str, message: str, data: dict | None = None) -> None:
        if category not in CATEGORIES:
            raise ValueError(f"unknown diagnostics category {category!r}")
        entry = {"at": self.clock().isoformat(), "category": category,
                 "message": redact_text(message), "data": _redact(data or {})}
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        segment = self._segment()
        with segment.open("a", encoding="utf-8") as handle:
            handle.write(line)
        if segment.stat().st_size >= _SEGMENT_BYTES:
            self.rotate()

    def _segment(self) -> Path:
        return self.directory / f"{self.clock().strftime('%Y%m%d')}.jsonl"

    # -- reading and bounds -------------------------------------------------------------------------

    def _segments(self) -> list[Path]:
        return sorted(p for p in self.directory.glob("*.jsonl") if p.is_file())

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self._segments())

    def recent(self, limit: int = 200) -> list[dict]:
        entries: list[dict] = []
        for segment in reversed(self._segments()):
            lines = segment.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines):
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue            # a torn line from a crash is skipped, never guessed at
                if len(entries) >= limit:
                    return list(reversed(entries))
        return list(reversed(entries))

    def rotate(self) -> int:
        """Drop what is too old, then what does not fit. Oldest first, both times (§43)."""
        removed = 0
        cutoff = self.clock() - self.max_age
        for segment in self._segments():
            day = datetime.strptime(segment.stem, "%Y%m%d").replace(tzinfo=UTC)
            if day < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
                segment.unlink()
                removed += 1

        segments = self._segments()
        while self.size_bytes() > self.max_bytes and segments:
            oldest = segments[0]
            if len(segments) == 1:
                self._trim(oldest)
                break
            oldest.unlink()
            removed += 1
            segments = self._segments()
        return removed

    def _trim(self, segment: Path) -> None:
        """The newest records survive: a single day's file is cut from the front, not thrown away."""
        lines = segment.read_text(encoding="utf-8").splitlines(keepends=True)
        while lines and sum(len(line.encode("utf-8")) for line in lines) > self.max_bytes:
            lines.pop(0)
        segment.write_text("".join(lines), encoding="utf-8")

    def clear(self) -> int:
        removed = 0
        for segment in self._segments():
            segment.unlink()
            removed += 1
        return removed

    def summary(self) -> dict:
        segments = self._segments()
        oldest = min((s.stem for s in segments), default=None)
        return {"entries": sum(1 for _ in self._iter_lines()), "size_bytes": self.size_bytes(),
                "oldest_day": oldest, "max_bytes": self.max_bytes,
                "max_age_days": int(self.max_age.total_seconds() // 86400),
                "directory": str(self.directory)}

    def _iter_lines(self):
        for segment in self._segments():
            with segment.open(encoding="utf-8") as handle:
                yield from handle


def open_store(data_dir: str | Path, **kwargs) -> DiagnosticsStore:
    return DiagnosticsStore(Path(data_dir) / "diagnostics", **kwargs)


class DiagnosticsHandler(logging.Handler):
    """Bridges what the application already logs into the local store (§43).

    The category comes from the logger's own name, so a network failure is filed as network and a job
    failure as job. Everything is redacted on the way in by the store itself; nothing here decides what
    is worth keeping beyond the four operational categories the Master names.
    """

    _BY_MODULE = {"net": "network", "sources": "network", "plugins": "parser", "generator": "parser",
                  "health": "health", "follow": "health"}

    def __init__(self, store: DiagnosticsStore) -> None:
        super().__init__()
        self.store = store
        self.addFilter(RedactingFilter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            parts = record.name.split(".")
            category = next((self._BY_MODULE[p] for p in parts if p in self._BY_MODULE), "job")
            data = {"logger": record.name, "level": record.levelname}
            if record.exc_info is not None:
                data["error"] = str(record.exc_info[1])
            self.store.record(category, record.getMessage(), data)
        except Exception:               # diagnostics must never break what they are observing
            pass
