"""Paddle Billing webhook handler.

Paddle Billing (v1, 2023+) signs webhooks with HMAC-SHA256. Header:
    Paddle-Signature: ts=1700000000;h1=<hex-digest>

Signed payload = f"{ts}:{raw_body}".encode()

On transaction.completed, we:
  1. Verify signature against PADDLE_WEBHOOK_SECRET
  2. Extract user_id + pack_id from custom_data (we set these on checkout)
  3. Call apply_paddle_topup() RPC — atomic insert + credit, idempotent
     on paddle_transaction_id.

Events we care about:
    transaction.completed  -> credit the user
    transaction.payment_failed -> no-op (Paddle handles retry)
    adjustment.created     -> if refund/chargeback, emit a negative ledger entry (TODO)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status

from .audit import audit
from .config import settings
from .db import service_client

log = logging.getLogger("paddle")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ─── Signature verification ────────────────────────────────────────
def _parse_paddle_sig(header: str) -> tuple[Optional[str], Optional[str]]:
    """Parse 'ts=..;h1=..' into (ts, h1)."""
    ts = h1 = None
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == "ts":
            ts = v
        elif k == "h1":
            h1 = v
    return ts, h1


def _verify_signature(secret: str, ts: str, raw_body: bytes, expected_h1: str) -> bool:
    """HMAC-SHA256 over f'{ts}:{body}', constant-time compare."""
    signed = f"{ts}:{raw_body.decode('utf-8')}".encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, expected_h1)


# ─── Handler ──────────────────────────────────────────────────────
@router.post("/paddle", status_code=status.HTTP_200_OK)
async def paddle_webhook(
    request: Request,
    paddle_signature: str | None = Header(default=None, alias="Paddle-Signature"),
):
    raw = await request.body()

    # Signature verification — the ONLY line between us and a
    # $-printing endpoint. Never skip in prod.
    if not settings.paddle_webhook_skip_verify:
        if not settings.paddle_webhook_secret:
            raise HTTPException(500, "Paddle webhook secret not configured")
        if not paddle_signature:
            raise HTTPException(401, "Missing Paddle-Signature header")
        ts, h1 = _parse_paddle_sig(paddle_signature)
        if not ts or not h1:
            raise HTTPException(401, "Malformed Paddle-Signature header")
        if not _verify_signature(settings.paddle_webhook_secret, ts, raw, h1):
            log.warning("paddle_bad_signature", extra={"ts": ts})
            audit(
                None, "billing.paddle_bad_signature",
                request=request, meta={"ts": ts},
            )
            raise HTTPException(401, "Invalid Paddle signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    event_type = payload.get("event_type") or ""
    event_id = payload.get("event_id") or ""
    data = payload.get("data") or {}

    log.info("paddle_event", extra={"event_type": event_type, "event_id": event_id})

    if event_type == "transaction.completed":
        return _handle_transaction_completed(event_id, data, payload, request)

    # Everything else: 200 OK, no-op. Paddle stops retrying on 2xx.
    return {"ok": True, "ignored": event_type}


def _handle_transaction_completed(
    event_id: str,
    data: dict[str, Any],
    raw: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Credit the user on a successful one-off purchase."""
    txn_id: str = data.get("id") or ""
    custom = (data.get("custom_data") or {}) or {}
    user_id = custom.get("user_id")
    pack_id = custom.get("pack_id")

    if not txn_id or not user_id or not pack_id:
        log.error(
            "paddle_missing_fields",
            extra={"txn_id": txn_id, "user_id": user_id, "pack_id": pack_id},
        )
        audit(
            user_id, "billing.paddle_missing_fields",
            subject_id=txn_id or None, request=request,
            meta={"pack_id": pack_id, "event_id": event_id},
        )
        # Return 200 so Paddle doesn't retry forever — we can't fix it.
        return {"ok": False, "reason": "missing_custom_data"}

    db = service_client()

    # Look up the pack to get canonical credit count + price.
    # NEVER trust the amount from the webhook payload — always resolve
    # from our DB using the pack_id we set at checkout.
    pack_resp = (
        db.table("credit_packs")
        .select("id, credits, price_usd, is_active")
        .eq("id", pack_id)
        .limit(1)
        .execute()
    )
    pack_row = (pack_resp.data or [None])[0]
    if not pack_row or not pack_row.get("is_active"):
        log.error("paddle_unknown_pack", extra={"pack_id": pack_id})
        audit(
            user_id, "billing.paddle_unknown_pack",
            subject_id=txn_id, request=request,
            meta={"pack_id": pack_id, "event_id": event_id},
        )
        return {"ok": False, "reason": "unknown_pack"}

    # Apply atomically via RPC. Idempotent on paddle_transaction_id.
    rpc = db.rpc(
        "apply_paddle_topup",
        {
            "p_paddle_transaction_id": txn_id,
            "p_paddle_event_id": event_id,
            "p_user_id": user_id,
            "p_pack_id": pack_id,
            "p_credits": pack_row["credits"],
            "p_price_usd": pack_row["price_usd"],
            "p_raw": raw,
        },
    ).execute()

    inserted_id = rpc.data
    if inserted_id is None:
        log.info("paddle_replay_ignored", extra={"txn_id": txn_id})
        audit(
            user_id, "billing.paddle_replay_ignored",
            subject_id=txn_id, request=request,
            meta={"pack_id": pack_id, "event_id": event_id},
        )
        return {"ok": True, "replay": True}

    log.info(
        "paddle_credited",
        extra={
            "user_id": user_id, "pack_id": pack_id,
            "credits": pack_row["credits"], "txn_id": txn_id,
        },
    )
    audit(
        user_id, "billing.paddle_credited",
        subject_id=txn_id, request=request,
        meta={
            "pack_id": pack_id,
            "credits": pack_row["credits"],
            "price_usd": pack_row["price_usd"],
            "event_id": event_id,
        },
    )
    return {"ok": True, "credited": pack_row["credits"], "transaction_id": inserted_id}
