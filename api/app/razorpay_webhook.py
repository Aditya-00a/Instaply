"""Razorpay payment handler — order creation + webhook.

Flow:
  1. User clicks Buy → frontend calls POST /billing/create-order
  2. API creates a Razorpay Order with pack metadata in notes
  3. Frontend opens Razorpay Checkout (JS overlay) with the order_id
  4. User completes payment
  5. Frontend sends payment_id + order_id + signature to POST /billing/verify-payment
  6. API verifies signature → looks up pack → credits the user

Razorpay verifies payments via HMAC-SHA256:
  generated_signature = hmac_sha256(order_id + "|" + payment_id, key_secret)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from .audit import audit
from .auth import current_user_id
from .config import settings
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("razorpay")

router = APIRouter(tags=["billing"])


def _razorpay_auth() -> tuple[str, str]:
    return (settings.razorpay_key_id, settings.razorpay_key_secret)


# ─── Create Order ────────────────────────────────────────────────
@router.post("/billing/create-order")
async def create_order(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("checkout", per_min=10),
):
    """Create a Razorpay Order for a credit pack purchase."""
    body = await request.json()
    pack_id = body.get("pack_id")
    if not pack_id:
        raise HTTPException(400, "pack_id is required")

    db = service_client()
    pack_resp = (
        db.table("credit_packs")
        .select("id, label, price_usd, credits, is_active")
        .eq("id", pack_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    pack_row = (pack_resp.data or [None])[0]
    if not pack_row:
        raise HTTPException(404, "Pack not found or inactive")

    # Razorpay amounts are in smallest currency unit (paise for INR, cents for USD)
    amount_cents = pack_row["price_usd"] * 100

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.razorpay.com/v1/orders",
                auth=_razorpay_auth(),
                json={
                    "amount": amount_cents,
                    "currency": "USD",
                    "notes": {
                        "user_id": user_id,
                        "pack_id": pack_id,
                        "credits": pack_row["credits"],
                        "source": "instaply_web",
                    },
                    "receipt": f"instaply_{pack_id}_{user_id[:8]}",
                },
                timeout=15,
            )
            resp.raise_for_status()
            order = resp.json()
    except httpx.HTTPStatusError as e:
        log.error("Razorpay order creation failed: %s %s", e.response.status_code, e.response.text[:200])
        raise HTTPException(500, "Payment order creation failed")
    except Exception as e:
        log.error("Razorpay error: %s", e)
        raise HTTPException(500, "Payment service unavailable")

    audit(
        user_id, "billing.order_created",
        request=request,
        meta={"pack_id": pack_id, "order_id": order["id"]},
    )

    return {
        "order_id": order["id"],
        "amount": amount_cents,
        "currency": "USD",
        "key_id": settings.razorpay_key_id,
        "pack": {
            "id": pack_row["id"],
            "label": pack_row["label"],
            "credits": pack_row["credits"],
        },
    }


# ─── Verify Payment ─────────────────────────────────────────────
@router.post("/billing/verify-payment")
async def verify_payment(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("verify_payment", per_min=20),
):
    """Verify Razorpay payment signature and credit the user."""
    body = await request.json()
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")

    if not order_id or not payment_id or not signature:
        raise HTTPException(400, "Missing payment verification fields")

    # Verify signature: HMAC-SHA256(order_id|payment_id, key_secret)
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        log.warning("razorpay_bad_signature: order=%s payment=%s", order_id, payment_id)
        audit(user_id, "billing.razorpay_bad_signature", request=request,
              meta={"order_id": order_id, "payment_id": payment_id})
        raise HTTPException(401, "Invalid payment signature")

    # Fetch order from Razorpay to get the pack metadata
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.razorpay.com/v1/orders/{order_id}",
                auth=_razorpay_auth(),
                timeout=10,
            )
            resp.raise_for_status()
            order = resp.json()
    except Exception as e:
        log.error("Failed to fetch order %s: %s", order_id, e)
        raise HTTPException(500, "Could not verify order details")

    notes = order.get("notes", {})
    pack_id = notes.get("pack_id")
    order_user_id = notes.get("user_id")

    if order_user_id != user_id:
        raise HTTPException(403, "Order does not belong to this user")

    if not pack_id:
        raise HTTPException(400, "Order missing pack metadata")

    # Look up pack
    db = service_client()
    pack_resp = (
        db.table("credit_packs")
        .select("id, credits, price_usd")
        .eq("id", pack_id)
        .limit(1)
        .execute()
    )
    pack_row = (pack_resp.data or [None])[0]
    if not pack_row:
        raise HTTPException(404, "Pack not found")

    # Idempotency: check if already credited
    existing = (
        db.table("credit_ledger")
        .select("id")
        .eq("note", f"razorpay:{payment_id}")
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"ok": True, "replay": True, "credits": pack_row["credits"]}

    # Credit the user
    db.table("credit_ledger").insert({
        "user_id": user_id,
        "delta": pack_row["credits"],
        "reason": "paid_topup",
        "note": f"razorpay:{payment_id}",
    }).execute()

    # Upgrade plan
    db.table("profiles").update({"plan": "pro"}).eq("id", user_id).eq("plan", "free").execute()

    log.info("razorpay_credited: user=%s pack=%s credits=%d payment=%s",
             user_id, pack_id, pack_row["credits"], payment_id)
    audit(user_id, "billing.razorpay_credited",
          subject_id=payment_id, request=request,
          meta={"pack_id": pack_id, "credits": pack_row["credits"],
                "price_usd": pack_row["price_usd"], "order_id": order_id})

    return {"ok": True, "credited": pack_row["credits"]}
