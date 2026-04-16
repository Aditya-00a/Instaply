"""Thin audit-log helper.

Call `audit(user_id, event, subject_id=..., meta={...})` from any handler
after a sensitive action completes. Never raises — a failed audit write
MUST NOT break the user-visible flow (we fall back to logging to stderr).
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional

from fastapi import Request

from .db import service_client

log = logging.getLogger("audit")

# Rotating salt so IPs can't be rainbow-tabled offline. Set in Fly secrets;
# rotate every 90 days. If empty, we simply don't store ip_hash.
_IP_SALT = os.getenv("AUDIT_IP_SALT", "")


def _hash_ip(ip: Optional[str]) -> Optional[str]:
    if not ip or not _IP_SALT:
        return None
    return hashlib.sha256(f"{_IP_SALT}:{ip}".encode("utf-8")).hexdigest()


def audit(
    user_id: Optional[str],
    event: str,
    *,
    subject_id: Optional[str] = None,
    request: Optional[Request] = None,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    ip = request.client.host if (request and request.client) else None
    ua = request.headers.get("user-agent") if request else None
    try:
        db = service_client()
        db.table("audit_log").insert({
            "user_id": user_id,
            "event": event,
            "subject_id": subject_id,
            "ip_hash": _hash_ip(ip),
            "user_agent": ua,
            "meta": meta or {},
        }).execute()
    except Exception:
        # Never propagate — audit is best-effort. Stderr fallback
        # so we can still grep logs for the event.
        log.exception("audit_write_failed event=%s user=%s", event, user_id)
