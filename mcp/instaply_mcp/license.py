"""License validation + free-trial counter for the Instaply MCP.

Honest contract:
  - First 5 applications are free. Counter lives in the local SQLite
    store at `~/.instaply/data.db` (table: license_usage).
  - After 5, the user needs a license JWT in `~/.instaply/license.jwt`
    (or via the INSTAPLY_LICENSE env var).
  - JWT is RS256-signed with a private key only the project owner has.
    The MCP package ships the matching PUBLIC key embedded below.
    Validation is 100% local — no network call, no license server,
    no dependency on instaply.asion.ai staying alive.
  - Buyer flow: user pays via a Razorpay Payment Link. The author (or
    the Cloudflare Worker once it ships) generates a per-email JWT and
    emails it. User saves it to `~/.instaply/license.jwt` once.

Why JWT + RS256:
  - JWT is a self-contained, signed payload — no validation server.
  - RS256 (asymmetric) means only the author can ISSUE keys; the MCP
    package only needs the public half to VERIFY. Buyers can't forge
    keys even with the package source.
  - If the author rotates keys later, old keys still work for users
    who already paid — JWT has no online revocation. (Honest trade:
    can't revoke a leaked key. For $25 software, acceptable.)

Security note for the project owner:
  - The private key (`license_signing_key.pem`) MUST live ONLY on the
    machine where you sign keys. NEVER check it into git.
  - The public key embedded below is safe to publish — it can only
    verify, not sign.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .db import _data_dir, connect


# ─── Free-trial limit + storage ─────────────────────────────────
FREE_TRIAL_APPLICATIONS = 5

# Embedded RSA public key. The author replaces this with their real
# public key before publishing v0.3 to PyPI. The placeholder below is
# intentionally invalid so any package shipped without a real key fails
# closed (free trial still works; paid validation always rejects until
# a real key is embedded).
LICENSE_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
PLACEHOLDER_REPLACE_BEFORE_FIRST_PUBLISH
-----END PUBLIC KEY-----
"""


def _license_path() -> Path:
    """Where the user keeps their license file. Override via
    INSTAPLY_LICENSE_PATH for tests."""
    override = os.environ.get("INSTAPLY_LICENSE_PATH")
    if override:
        return Path(override).expanduser()
    return _data_dir() / "license.jwt"


def _ensure_usage_table() -> None:
    with connect() as c, c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS license_usage ("
            "  id INTEGER PRIMARY KEY CHECK (id = 1),"
            "  applications_used INTEGER NOT NULL DEFAULT 0,"
            "  first_used_at TEXT,"
            "  last_used_at TEXT"
            ")"
        )


def _read_license_token() -> Optional[str]:
    """Resolve the license JWT from env var first, then file."""
    env = os.environ.get("INSTAPLY_LICENSE", "").strip()
    if env:
        return env
    p = _license_path()
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return None
    return None


def _verify_jwt(token: str) -> tuple[bool, Optional[dict], Optional[str]]:
    """Returns (ok, payload, error_message). PyJWT lazily imported so
    free-tier users without a license never pay the import cost."""
    try:
        import jwt  # PyJWT
    except ImportError:
        return False, None, (
            "license verification requires PyJWT — install with "
            "`pip install 'instaply-mcp[license]'`"
        )

    if b"PLACEHOLDER" in LICENSE_PUBLIC_KEY_PEM:
        return False, None, (
            "this build of instaply-mcp ships without a real license "
            "verification key (placeholder still in source). The "
            "free-trial path still works; paid validation is disabled."
        )
    try:
        payload = jwt.decode(
            token,
            LICENSE_PUBLIC_KEY_PEM,
            algorithms=["RS256"],
            options={"require": ["sub", "iat"]},
        )
        return True, payload, None
    except Exception as e:
        return False, None, f"license_invalid: {type(e).__name__}: {str(e)[:120]}"


# ─── Public API used by the runner ─────────────────────────────
def license_status() -> dict:
    """Snapshot of the user's licensing state. Safe to call cheaply."""
    _ensure_usage_table()
    with connect() as c:
        row = c.execute(
            "SELECT applications_used FROM license_usage WHERE id = 1"
        ).fetchone()
        used = row["applications_used"] if row else 0

    token = _read_license_token()
    if token:
        ok, payload, err = _verify_jwt(token)
        if ok:
            return {
                "licensed": True,
                "trial_used": used,
                "trial_remaining": None,
                "license_email": (payload or {}).get("sub"),
                "issued_at": (payload or {}).get("iat"),
            }
        # Token present but invalid → don't unlock; report why.
        return {
            "licensed": False,
            "trial_used": used,
            "trial_remaining": max(0, FREE_TRIAL_APPLICATIONS - used),
            "license_error": err,
        }

    return {
        "licensed": False,
        "trial_used": used,
        "trial_remaining": max(0, FREE_TRIAL_APPLICATIONS - used),
    }


def consume_one_application() -> tuple[bool, str]:
    """Charge one application against the trial counter (or pass through
    if licensed). Returns (allowed, message).

    Call this from `apply_to_job` BEFORE doing real work. If it returns
    (False, msg), surface msg to the user and do not run.
    """
    status = license_status()
    if status["licensed"]:
        return True, "licensed"

    used = status["trial_used"]
    if used >= FREE_TRIAL_APPLICATIONS:
        return False, (
            f"Free trial used ({used}/{FREE_TRIAL_APPLICATIONS} applications). "
            "Buy a one-time license to keep going. Visit "
            "https://instaply.asion.ai/buy (Razorpay) and paste the key "
            "you receive into ~/.instaply/license.jwt or set the "
            "INSTAPLY_LICENSE env var."
        )

    _ensure_usage_table()
    with connect() as c, c:
        c.execute(
            "INSERT INTO license_usage (id, applications_used, first_used_at, last_used_at) "
            "VALUES (1, 1, datetime('now'), datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  applications_used = applications_used + 1, "
            "  last_used_at = datetime('now')"
        )
    remaining = FREE_TRIAL_APPLICATIONS - used - 1
    return True, f"trial:{used + 1}/{FREE_TRIAL_APPLICATIONS} (remaining: {remaining})"
