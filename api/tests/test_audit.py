"""Verify audit() fires on sensitive actions with the right event names."""
from __future__ import annotations

from .conftest import make_jwt


def test_mcp_token_create_emits_audit(client, fake_db, monkeypatch, jwt_secret):
    from app.tests.conftest import FakeQuery
    fake_db.tables["mcp_tokens"] = FakeQuery(
        rows=[{
            "id": "tok-xyz", "label": "claude-desktop",
            "created_at": "2026-04-15T00:00:00Z",
            "expires_at": "2026-10-15T00:00:00Z",
        }]
    )
    events: list[tuple] = []
    from app import main as mainmod
    monkeypatch.setattr(
        mainmod, "audit",
        lambda uid, event, **kw: events.append((uid, event, kw)),
    )
    token = make_jwt("user-abc", jwt_secret)
    r = client.post(
        "/auth/mcp-tokens", json={"label": "claude-desktop"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert any(e[1] == "auth.mcp_token_created" for e in events)
    assert events[-1][0] == "user-abc"
    assert events[-1][2]["subject_id"] == "tok-xyz"


def test_mcp_token_revoke_emits_audit(client, fake_db, monkeypatch, jwt_secret):
    from app.tests.conftest import FakeQuery
    fake_db.tables["mcp_tokens"] = FakeQuery(rows=[])
    events: list[tuple] = []
    from app import main as mainmod
    monkeypatch.setattr(
        mainmod, "audit",
        lambda uid, event, **kw: events.append((uid, event, kw)),
    )
    token = make_jwt("user-abc", jwt_secret)
    r = client.delete(
        "/auth/mcp-tokens/tok-xyz",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert any(e[1] == "auth.mcp_token_revoked" for e in events)


def test_profile_update_emits_audit(client, fake_db, monkeypatch, jwt_secret):
    from app.tests.conftest import FakeQuery
    fake_db.tables["profiles"] = FakeQuery(rows=[])
    events: list[tuple] = []
    from app import main as mainmod
    monkeypatch.setattr(
        mainmod, "audit",
        lambda uid, event, **kw: events.append((uid, event, kw)),
    )
    token = make_jwt("user-abc", jwt_secret)
    r = client.patch(
        "/profile", json={"phone_e164": "+15555550123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert any(e[1] == "profile.updated" for e in events)
    assert events[-1][2]["meta"] == {"fields": ["phone_e164"]}


def test_paddle_bad_signature_emits_audit(client, monkeypatch):
    """Forces the bad-signature path and checks audit fires with user_id=None."""
    events: list[tuple] = []
    from app import paddle as paddlemod
    monkeypatch.setattr(
        paddlemod, "audit",
        lambda uid, event, **kw: events.append((uid, event, kw)),
    )
    # Don't skip signature verify in this test
    from app import config as cfgmod
    monkeypatch.setattr(cfgmod.settings, "paddle_webhook_skip_verify", False)
    monkeypatch.setattr(cfgmod.settings, "paddle_webhook_secret", "test-wh-secret")
    r = client.post(
        "/webhooks/paddle",
        content=b'{"event_type":"transaction.completed"}',
        headers={"Paddle-Signature": "ts=12345;h1=deadbeef"},
    )
    assert r.status_code == 401
    assert any(e[1] == "billing.paddle_bad_signature" for e in events)
    assert events[-1][0] is None  # no user for unauthenticated bad sig
