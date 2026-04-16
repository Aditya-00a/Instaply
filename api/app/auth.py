"""Bearer-token auth.

Two token types accepted:
  1. Supabase JWT (short-lived HS256) — for the web dashboard
  2. Instaply MCP token (long-lived opaque, prefix 'ia_') — for Claude Desktop

Supabase JWTs MUST be signature-verified with SUPABASE_JWT_SECRET.
Previously we used get_unverified_claims() — that's a footgun and is only
acceptable behind `settings.auth_skip_jwt_verify = True` for local dev.

MCP tokens are looked up by sha256 via the resolve_mcp_token RPC, which
also checks expiry + revocation. We stamp last_used_at on success.
"""
from __future__ import annotations

import hashlib

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt

from .config import settings
from .db import service_client


MCP_TOKEN_PREFIX = "ia_"


def _looks_like_mcp_token(token: str) -> bool:
    return token.startswith(MCP_TOKEN_PREFIX)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


async def current_user_id(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Empty bearer token")

    # ─ MCP opaque tokens ────────────────────────────────────────
    if _looks_like_mcp_token(token):
        return await _resolve_mcp_token(token)

    # ─ Supabase JWT ─────────────────────────────────────────────
    return _verify_supabase_jwt(token)


def _verify_supabase_jwt(token: str) -> str:
    """Verify signature + expiry + audience, return user id (sub claim).

    Supabase issues HS256 tokens by default. The secret is NOT the anon
    key — it's the separate JWT Secret in the API settings. Never expose
    that secret to clients.
    """
    if settings.auth_skip_jwt_verify:
        # Dev escape hatch ONLY. Logs a warning on every request.
        import logging
        logging.getLogger("auth").warning("JWT verification skipped (dev mode)")
        claims = jwt.get_unverified_claims(token)
        sub = claims.get("sub")
        if not sub:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No sub claim")
        return sub

    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "SUPABASE_JWT_SECRET not configured; cannot verify tokens.",
        )

    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
            options={"require": ["exp", "sub"]},
        )
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token claims")
    return sub


async def _resolve_mcp_token(token: str) -> str:
    db = service_client()
    h = _sha256_hex(token)
    try:
        resp = db.rpc("resolve_mcp_token", {"p_token_hash": h}).execute()
    except Exception as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"MCP token check failed: {e}")
    user_id = resp.data
    if not user_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "MCP token invalid, revoked, or expired. Generate a new one at "
            "instaply.asion.ai/settings/mcp",
        )
    return str(user_id)
