"""Extension-assisted manual completion endpoint.

When the Instaply Chrome extension fills a captcha/verification-blocked
application in the user's own browser AND observes that the page
navigated to a confirmation URL after the user clicked Submit, it
posts back here to mark the application as submitted with
`submitter_kind='extension'`.

This is the auto-reporting equivalent of the dashboard's
`I submitted this manually` button — same final row state, same
preserved audit trail (submission_log + screenshot_url + error_message
all stay intact). The difference is the trigger: the user doesn't have
to remember to come back to the dashboard and click anything.

Conservative on purpose:
  - Endpoint is auth-gated by JWT (the same `current_user_id` everything
    else uses) — only the row's owner can mark it submitted.
  - Only flips `failed`, `needs_review`, `skipped` rows. Refuses to
    touch `in_progress` (would race the worker), `submitted`,
    `confirmed`, `queued` (already healthy).
  - Stores `submitter_kind='extension'` (already in the
    `applications_submitter_kind_check` allow-list per migration 0014).
  - Does NOT trust the extension's claim about WHICH page it saw — the
    only signal we accept is "user wants this row marked submitted."
    The captcha/verification gate already proved a human was at the
    keyboard.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from .auth import current_user_id
from .db import service_client
from .ratelimit import rate_limit

log = logging.getLogger("extension_finish")
router = APIRouter(tags=["applications"])


@router.post("/applications/{app_id}/extension-finish")
async def extension_finish(
    request: Request,
    app_id: str = Path(..., min_length=8, max_length=64),
    user_id: str = Depends(current_user_id),
    _rl: None = rate_limit("extension_finish", per_min=30),
):
    """Mark an extension-completed application as submitted.

    Returns 404 if the row doesn't exist for this user, 409 if it's in
    a state we refuse to overwrite (in_progress / submitted / confirmed
    / queued), 200 with the updated shape on success.
    """
    db = service_client()

    # Fetch + ownership + state check in one hop.
    existing = (
        db.table("applications")
        .select("id, status, submitter_kind, completed_at")
        .eq("id", app_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "application_not_found")

    row = existing.data[0]
    current_status = row.get("status")
    if current_status in ("in_progress", "submitted", "confirmed", "queued"):
        # Idempotent for already-submitted rows: return current shape
        # so a double-click from the extension doesn't error out.
        if current_status in ("submitted", "confirmed"):
            return {
                "ok": True,
                "already_submitted": True,
                "application_id": app_id,
                "status": current_status,
            }
        raise HTTPException(
            409,
            f"refusing_to_overwrite_status:{current_status}",
        )

    # PATCH: status='submitted', submitter_kind='extension', completed_at=now().
    # Intentionally NOT clearing submission_log / screenshot_url /
    # error_message — those record what the worker attempted before
    # the extension took over and are useful for support diagnostics.
    result = (
        db.table("applications")
        .update({
            "status": "submitted",
            "submitter_kind": "extension",
            "completed_at": "now()",
        })
        .eq("id", app_id)
        .eq("user_id", user_id)
        # Re-assert the state filter so we can't race a concurrent
        # worker writeback. PATCH .in_() against the eligible-for-finish
        # set; if a concurrent transition already moved it elsewhere,
        # zero rows update and we surface a 409.
        .in_("status", ["failed", "needs_review", "skipped"])
        .execute()
    )

    if not result.data:
        # The pre-check passed but the PATCH found zero rows — concurrent
        # state transition happened between SELECT and UPDATE. Return
        # the current state so the extension can decide what to do.
        latest = (
            db.table("applications")
            .select("status")
            .eq("id", app_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        latest_status = (latest.data or [{}])[0].get("status", "unknown")
        raise HTTPException(409, f"raced_with_concurrent_update:{latest_status}")

    log.info(
        "extension_finish",
        extra={"application_id": app_id, "user_id": user_id, "from_status": current_status},
    )
    return {
        "ok": True,
        "already_submitted": False,
        "application_id": app_id,
        "status": "submitted",
    }
