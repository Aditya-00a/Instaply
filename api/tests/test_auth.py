"""Auth verification — JWT signature, MCP-token RPC lookup."""
from __future__ import annotations

from .conftest import make_jwt


def test_valid_jwt_allows_request(client, fake_db, jwt_secret):
    fake_db.rpcs["get_credit_balance"] = 5
    from app.tests.conftest import FakeQuery  # noqa: E402
    fake_db.tables["profiles"] = FakeQuery(rows={"plan": "free"})
    token = make_jwt("user-123", jwt_secret)
    r = client.get("/credits", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["balance"] == 5


def test_expired_jwt_rejected(client, jwt_secret):
    token = make_jwt("user-123", jwt_secret, exp_delta=-10)
    r = client.get("/credits", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_bad_signature_rejected(client):
    token = make_jwt("user-123", "wrong-secret")
    r = client.get("/credits", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_missing_bearer_rejected(client):
    r = client.get("/credits")
    # FastAPI converts the missing Header(...) into 422 or 401 depending on version
    assert r.status_code in (401, 422)


def test_mcp_token_resolves_via_rpc(client, fake_db):
    fake_db.rpcs["resolve_mcp_token"] = "user-from-mcp"
    fake_db.rpcs["get_credit_balance"] = 7
    from app.tests.conftest import FakeQuery
    fake_db.tables["profiles"] = FakeQuery(rows={"plan": "free"})
    r = client.get("/credits", headers={"Authorization": "Bearer ia_abc123"})
    assert r.status_code == 200
    assert r.json()["balance"] == 7


def test_mcp_token_unknown_rejected(client, fake_db):
    fake_db.rpcs["resolve_mcp_token"] = None
    r = client.get("/credits", headers={"Authorization": "Bearer ia_ghost"})
    assert r.status_code == 401
