"""Bearer-token auth.

Two token types accepted:
  1. Supabase JWT (ES256 signed) — for the web dashboard
  2. Instaply MCP token (long-lived opaque, prefix 'ia_') — for Claude Desktop

Supabase JWTs are verified via the project's JWKS endpoint (ES256 public key).
MCP tokens are looked up by sha256 via the resolve_mcp_token RPC.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx
from fastapi import Header, HTTPException, status
from jose import jwt, jwk, JWTError

from .config import settings
from .db import service_client

log = logging.getLogger("auth")

MCP_TOKEN_PREFIX = "ia_"

# JWKS cache — refreshed every 10 minutes
_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0
_JWKS_TTL = 600  # 10 minutes


def _looks_like_mcp_token(token: str) -> bool:
    return token.startswith(MCP_TOKEN_PREFIX)


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _get_jwks() -> dict[str, Any]:
    """Fetch and cache JWKS from Supabase."""
    global _jwks_cache, _jwks_fetched_at

    if _jwks_cache and (time.time() - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache

    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        resp = httpx.get(jwks_url, headers={"apikey": settings.supabase_anon_key}, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = time.time()
        return _jwks_cache
    except Exception as e:
        log.error("Failed to fetch JWKS: %s", e)
        if _jwks_cache:
            return _jwks_cache  # stale cache is better than nothing
        raise HTTPException(500, "Could not fetch signing keys")


async def current_user_id(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Empty bearer token")

    # MCP opaque tokens
    if _looks_like_mcp_token(token):
        return await _resolve_mcp_token(token)

    # Supabase JWT
    return _verify_supabase_jwt(token)


def _verify_supabase_jwt(token: str) -> str:
    """Verify Supabase JWT using JWKS (ES256) or legacy HMAC secret."""
    if settings.auth_skip_jwt_verify:
        log.warning("JWT verification skipped (dev mode)")
        claims = jwt.get_unverified_claims(token)
        sub = claims.get("sub")
        if not sub:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No sub claim")
        return sub

    # Peek at the JWT header to determine algorithm
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token header: {e}")

    alg = unverified_header.get("alg", "")
    kid = unverified_header.get("kid")

    if alg == "ES256":
        return _verify_es256(token, kid)
    elif alg in ("HS256", "HS384", "HS512"):
        return _verify_hmac(token, alg)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Unsupported JWT algorithm: {alg}")


def _verify_es256(token: str, kid: str | None) -> str:
    """Verify ES256 JWT using Supabase JWKS."""
    jwks_data = _get_jwks()
    keys = jwks_data.get("keys", [])

    # Find the matching key by kid
    key_data = None
    for k in keys:
        if kid and k.get("kid") == kid:
            key_data = k
            break
    if not key_data and keys:
        key_data = keys[0]  # fallback to first key

    if not key_data:
        raise HTTPException(500, "No suitable signing key found in JWKS")

    try:
        public_key = jwk.construct(key_data, algorithm="ES256")
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            audience=settings.supabase_jwt_audience,
            options={"require": ["exp", "sub"]},
        )
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token claims")
    return sub


def _verify_hmac(token: str, alg: str) -> str:
    """Verify HMAC-signed JWT with the legacy JWT secret."""
    if not settings.supabase_jwt_secret:
        raise HTTPException(500, "SUPABASE_JWT_SECRET not configured")

    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[alg],
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
