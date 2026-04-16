"""Verify the rate limiter actually triggers 429s on the wired routes."""
from __future__ import annotations

from .conftest import make_jwt


def test_billing_packs_anon_limit(client, fake_db):
    # /billing/packs has per_min=60 anon (IP-bucketed).
    from app.tests.conftest import FakeQuery
    fake_db.tables["credit_packs"] = FakeQuery(rows=[])
    # Shrink the limit for this test by directly updating settings? Easier:
    # just hit it 61 times — in-process, so it'll be fast.
    statuses = [client.get("/billing/packs").status_code for _ in range(65)]
    assert statuses.count(200) == 60
    assert statuses.count(429) == 5


def test_mcp_token_mint_strict_limit(client, fake_db, jwt_secret):
    # /auth/mcp-tokens POST is 10/min — mint abuse target.
    from app.tests.conftest import FakeQuery
    fake_db.tables["mcp_tokens"] = FakeQuery(
        rows=[{
            "id": "tok-1", "label": "test", "created_at": "2026-04-15T00:00:00Z",
            "expires_at": "2026-10-15T00:00:00Z",
        }]
    )
    token = make_jwt("user-abc", jwt_secret)
    h = {"Authorization": f"Bearer {token}"}
    statuses = [
        client.post("/auth/mcp-tokens", json={"label": f"l{i}"}, headers=h).status_code
        for i in range(12)
    ]
    assert statuses.count(429) >= 2  # at least 2 rejections after 10 mints
