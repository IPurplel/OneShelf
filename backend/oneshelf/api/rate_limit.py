"""Per-IP sliding-window rate limiter for sensitive endpoints (BKD-003)."""
from __future__ import annotations

import time
import threading
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response


class RateLimiter:
    def __init__(self, window_seconds: float = 60.0, max_requests: int = 10,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.window = window_seconds
        self.max_requests = max_requests
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = clock()

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self.window:
            return
        self._last_cleanup = now
        cutoff = now - self.window
        for ip in list(self._hits):
            self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]
            if not self._hits[ip]:
                del self._hits[ip]

    def check(self, ip: str) -> float | None:
        now = self.clock()
        with self._lock:
            self._cleanup(now)
            cutoff = now - self.window
            timestamps = self._hits[ip]
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self.max_requests:
                return self.window - (now - timestamps[0])
            timestamps.append(now)
            return None


_auth_limiter = RateLimiter(window_seconds=60, max_requests=10)
_recovery_limiter = RateLimiter(window_seconds=60, max_requests=3)


def _client_ip(request: Request) -> str:
    return request.scope["state"].get("real_ip") or (request.client.host if request.client else "unknown")


def require_auth_rate_limit(request: Request) -> Response | None:
    retry_after = _auth_limiter.check(_client_ip(request))
    if retry_after is None:
        return None
    return Response(status_code=429, headers={"Retry-After": str(int(retry_after) + 1)})


def require_recovery_rate_limit(request: Request) -> Response | None:
    retry_after = _recovery_limiter.check(_client_ip(request))
    if retry_after is None:
        return None
    return Response(status_code=429, headers={"Retry-After": str(int(retry_after) + 1)})
