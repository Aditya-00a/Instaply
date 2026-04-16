"""Stripe webhook handler + Checkout Session creator.

Stripe signs webhooks with HMAC-SHA256 via the Stripe-Signature header.
We use the `stripe` Python SDK for verification and session creation.

Flow:
  1. User clicks Buy → frontend calls POST /billing/create-checkout
  2. API creates a Stripe Checkout Session with pack metadata
  3. User completes payment on Stripe's hosted page
  4. Stripe sends checkout.session.completed webhook
  5. We verify signature → look up pack → credit the user

Events we handle:
    checkout.session.completed  → credit the user
    charge.refunded             → negative ledger entry (TODO)
"""
from __future__ import annotations

import json
import logging
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status

from .audit import audit
from .auth import current_user_id
from .config import settings
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("stripe_webhook")

router = APIRouter(tags=["billing"])

# Configure Stripe SDK
stripe.api_key = settings.stripe_secret_key


# ─── Create Checkout Session ─────────────────────────────────────
@router.post("/billing/create-checkout")
async def create_checkout(
    request: Request,
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("checkout", per_min=10),
):
    """Create a Stripe Checkout Session for a credit pack purchase."""
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

    # Get user email for Stripe
    prof = db.table("profiles").select("email").eq("id", user_id).single().execute()
    email = prof.data.get("email") if prof.data else None

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": pack_row["price_usd"] * 100,  # cents
                    "product_data": {
                        "name": f"Instaply {pack_row['label']} — {pack_row['credits']} applications",
                        "description": f"${pack_row['price_usd']} for {pack_row['credits']} confirmed job applications",
                    },
                },
                "quantity": 1,
            }],
            metadata={
                "user_id": user_id,
                "pack_id": pack_id,
            },
            customer_email=email,
            success_url=f"{settings.web_url}/billing?success=1",
            cancel_url=f"{settings.web_url}/billing?cancelled=1",
        )
    except stripe.StripeError as e:
        log.error("Stripe session creation failed: %s", e)
        raise HTTPException(500, "Payment session creation failed")

    audit(
        user_id, "billing.checkout_created",
        request=request,
        meta={"pack_id": pack_id, "session_id": session.id},
    )

    return {"checkout_url": session.url, "session_id": session.id}


# ─── Webhook Handler ─────────────────────────────────────────────
@router.post("/webhooks/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("Stripe-Signature")

    # Verify signature
    if not settings.stripe_webhook_skip_verify:
        if not settings.stripe_webhook_secret:
            raise HTTPException(500, "Stripe webhook secret not configured")
        if not sig:
            raise HTTPException(401, "Missing Stripe-Signature header")
        try:
            event = stripe.Webhook.construct_event(
                raw, sig, settings.stripe_webhook_secret
            )
        except stripe.SignatureVerificationError:
            log.warning("stripe_bad_signature")
            audit(None, "billing.stripe_bad_signature", request=request)
            raise HTTPException(401, "Invalid Stripe signature")
        except Exception as e:
            raise HTTPException(400, f"Webhook error: {e}")
    else:
        try:
            event = json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(400, "Invalid JSON")

    event_type = event.get("type", "") if isinstance(event, dict) else event.type
    log.info("stripe_event: %s", event_type)

    if event_type == "checkout.session.completed":
        data = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object
        return _handle_checkout_completed(data, request)

    return {"ok": True, "ignored": event_type}


def _handle_checkout_completed(
    session: Any,
    request: Request,
) -> dict[str, Any]:
    """Credit the user after successful Stripe checkout."""
    session_id = session.get("id", "") if isinstance(session, dict) else session.id
    metadata = session.get("metadata", {}) if isinstance(session, dict) else (session.metadata or {})
    user_id = metadata.get("user_id")
    pack_id = metadata.get("pack_id")

    if not session_id or not user_id or not pack_id:
        log.error("stripe_missing_metadata: session=%s user=%s pack=%s", session_id, user_id, pack_id)
        audit(user_id, "billing.stripe_missing_metadata", request=request,
              meta={"session_id": session_id, "pack_id": pack_id})
        return {"ok": False, "reason": "missing_metadata"}

    db = service_client()

    # Look up pack for canonical credit count
    pack_resp = (
        db.table("credit_packs")
        .select("id, credits, price_usd, is_active")
        .eq("id", pack_id)
        .limit(1)
        .execute()
    )
    pack_row = (pack_resp.data or [None])[0]
    if not pack_row or not pack_row.get("is_active"):
        log.error("stripe_unknown_pack: %s", pack_id)
        audit(user_id, "billing.stripe_unknown_pack",
              subject_id=session_id, request=request, meta={"pack_id": pack_id})
        return {"ok": False, "reason": "unknown_pack"}

    # Idempotency: check if we already credited this session
    existing = (
        db.table("credit_ledger")
        .select("id")
        .eq("note", f"stripe:{session_id}")
        .limit(1)
        .execute()
    )
    if existing.data:
        log.info("stripe_replay_ignored: %s", session_id)
        return {"ok": True, "replay": True}

    # Credit the user
    db.table("credit_ledger").insert({
        "user_id": user_id,
        "delta": pack_row["credits"],
        "reason": "paid_topup",
        "note": f"stripe:{session_id}",
    }).execute()

    # Upgrade plan if needed
    db.table("profiles").update({"plan": "pro"}).eq("id", user_id).eq("plan", "free").execute()

    log.info("stripe_credited: user=%s pack=%s credits=%d", user_id, pack_id, pack_row["credits"])
    audit(user_id, "billing.stripe_credited",
          subject_id=session_id, request=request,
          meta={"pack_id": pack_id, "credits": pack_row["credits"], "price_usd": pack_row["price_usd"]})

    return {"ok": True, "credited": pack_row["credits"]}
