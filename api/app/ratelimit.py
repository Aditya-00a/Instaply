"""In-process rate limiter — sliding window, per-user or per-IP.

Why in-process and not Redis?
  - Fly scales the API to 0–2 machines in MVP; in-process is accurate
    enough for our threat model (abuse of free credits, credential stuffing).
  - When we go multi-machine we swap this for a Redis-backed sliding window
    without touching call sites.

Usage:
    from .ratelimit import rate_limit

    @app.post("/applications")
    async def queue_app(
        req: ..., user_id: str = Depends(current_user_id),
        _rl: None = Depends(rate_limit("queue_app", per_min=30)),
    ):
        ...
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Optional

from fastapi import Depends, HTTPException, Request, status

from .config import settings

# (bucket_key -> deque of timestamps in seconds)
_WINDOWS: dict[str, Deque[float]] = defaultdict(deque)
_WINDOW_SECONDS = 60.0


def _prune(q: Deque[float], now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    while q and q[0] < cutoff:
        q.popleft()


def _check(bucket_key: str, limit: int) -> None:
    now = time.monotonic()
    q = _WINDOWS[bucket_key]
    _prune(q, now)
    if len(q) >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded ({limit}/min). Try again in a minute.",
        )
    q.append(now)


def rate_limit(
    scope: str,
    *,
    per_min: Optional[int] = None,
    anon: bool = False,
) -> Callable:
    """Dependency factory. `scope` isolates buckets per endpoint group.

    With `anon=True`, buckets by client IP (for unauthenticated routes
    like /billing/packs). Otherwise requires Authorization header and
    buckets by the bearer token (hash) so we don't decode the JWT twice.
    """
    limit = per_min or (
        settings.rate_limit_anon_per_min if anon else settings.rate_limit_per_min
    )

    async def _dep(request: Request) -> None:
        if anon:
            ip = request.client.host if request.client else "unknown"
            _check(f"{scope}:ip:{ip}", limit)
            return
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            # Let the auth dependency produce the real 401.
            return
        # Hash the token so we don't keep plaintext in a process dict.
        import hashlib
        tok = auth.removeprefix("Bearer ").strip()
        key = hashlib.blake2b(tok.encode("utf-8"), digest_size=16).hexdigest()
        _check(f"{scope}:tok:{key}", limit)

    return Depends(_dep)
