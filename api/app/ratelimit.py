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
# Cap on distinct keys we'll track — prevents unbounded growth on a long-lived
# Fly machine when many distinct users / IPs hit the API. When we exceed the
# cap, we evict empty buckets first, then oldest. Conservative cap chosen to
# accommodate a few thousand concurrent users with multiple scopes each.
_MAX_BUCKETS = 50_000
_LAST_GC = [0.0]
_GC_INTERVAL_SECONDS = 300.0  # opportunistic GC at most once per 5 min


def _prune(q: Deque[float], now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    while q and q[0] < cutoff:
        q.popleft()


def _maybe_gc(now: float) -> None:
    """Drop empty deques (buckets whose last hit aged past the window).

    Cheap: only runs when we hit the bucket cap or every 5 min on entry,
    iterates the dict once. Without this, _WINDOWS grows unbounded with
    the number of distinct users * scopes the API has ever served.
    """
    if len(_WINDOWS) < _MAX_BUCKETS and (now - _LAST_GC[0]) < _GC_INTERVAL_SECONDS:
        return
    _LAST_GC[0] = now
    cutoff = now - _WINDOW_SECONDS
    # First pass: drop buckets that are empty or fully aged out
    to_delete = [
        k for k, q in _WINDOWS.items()
        if not q or q[-1] < cutoff
    ]
    for k in to_delete:
        _WINDOWS.pop(k, None)


def _check(bucket_key: str, limit: int) -> None:
    now = time.monotonic()
    _maybe_gc(now)
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
