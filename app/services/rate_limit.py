from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock

from fastapi import HTTPException, Request, status

from app.config import settings

RATE_LIMIT_MESSAGE = "Too many requests. Please try again later."


@dataclass
class _Window:
    started_at: datetime
    count: int = 0


@dataclass
class _InMemoryRateLimiter:
    # For multi-worker production, replace this with Redis or another shared store.
    windows: dict[str, _Window] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = datetime.utcnow()
        with self.lock:
            window = self.windows.get(key)
            if window is None or now - window.started_at >= timedelta(seconds=window_seconds):
                self.windows[key] = _Window(started_at=now, count=1)
                return True

            if window.count >= limit:
                return False

            window.count += 1
            return True

    def reset(self) -> None:
        with self.lock:
            self.windows.clear()


_limiter = _InMemoryRateLimiter()


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _clean_part(value: str | None) -> str:
    return (value or "").strip().lower()


def assert_rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    window_seconds: int,
    *identity_parts: str | None,
) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return

    parts = [bucket, _client_ip(request), *(_clean_part(part) for part in identity_parts)]
    key = ":".join(parts)
    if not _limiter.hit(key=key, limit=limit, window_seconds=window_seconds):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=RATE_LIMIT_MESSAGE,
        )


def reset_rate_limits() -> None:
    _limiter.reset()
