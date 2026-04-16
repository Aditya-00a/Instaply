"""Shared fixtures for API tests.

We isolate from real Supabase by monkeypatching `service_client` with a
fake chainable object. We also set config secrets BEFORE importing the
app so pydantic-settings picks them up.
"""
from __future__ import annotations

import os
import sys
import pathlib
from typing import Any

import pytest

# Ensure config loads with a known JWT secret BEFORE `app` imports run.
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-do-not-use-in-prod")
os.environ.setdefault("NVIDIA_NIM_API_KEY", "unused-in-tests")
os.environ.setdefault("AUDIT_IP_SALT", "test-salt")

# Make `from app import ...` work when running pytest from repo root.
_API_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_API_DIR))


class FakeResponse:
    def __init__(self, data: Any = None):
        self.data = data


class FakeQuery:
    """Chainable stub — records the call chain and returns configurable data."""
    def __init__(self, rows: list | dict | int | None = None):
        self._rows = rows

    def _chain(self, *_a, **_kw):
        return self

    # All the chainable methods used by the API code
    select = update = insert = delete = _chain
    eq = ilike = order = limit = single = _chain

    def execute(self):
        return FakeResponse(self._rows)


class FakeDB:
    """Stand-in for the supabase client. Table/rpc dispatch configurable per-test."""
    def __init__(self):
        self.tables: dict[str, Any] = {}
        self.rpcs: dict[str, Any] = {}
        self.inserted: list[tuple[str, dict]] = []

    def table(self, name: str):
        q = self.tables.get(name, FakeQuery(rows=[]))
        # Wrap insert to record what got written (used by audit assertions).
        real_insert = q.insert

        def _insert(payload, *a, **kw):
            self.inserted.append((name, payload))
            return real_insert(payload, *a, **kw)

        q.insert = _insert
        return q

    def rpc(self, name: str, params: dict | None = None):
        data = self.rpcs.get(name)
        return FakeQuery(rows=data() if callable(data) else data)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    # Patch both callsites: main module + audit module.
    from app import db as dbmod, audit as auditmod, paddle as paddlemod
    monkeypatch.setattr(dbmod, "service_client", lambda: db)
    monkeypatch.setattr(auditmod, "service_client", lambda: db)
    monkeypatch.setattr(paddlemod, "service_client", lambda: db)
    # main.py uses `from .db import service_client` — patch that too.
    from app import main as mainmod
    monkeypatch.setattr(mainmod, "service_client", lambda: db)
    return db


@pytest.fixture(autouse=True)
def reset_rate_limit_windows():
    """Each test gets a clean slate so bucket state doesn't leak across tests."""
    from app import ratelimit
    ratelimit._WINDOWS.clear()
    yield
    ratelimit._WINDOWS.clear()


@pytest.fixture
def client(fake_db):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture
def jwt_secret():
    return os.environ["SUPABASE_JWT_SECRET"]


def make_jwt(sub: str, secret: str, *, exp_delta: int = 3600, aud: str = "authenticated") -> str:
    """Mint a Supabase-style HS256 access token for tests."""
    import time
    from jose import jwt
    claims = {
        "sub": sub,
        "aud": aud,
        "exp": int(time.time()) + exp_delta,
        "iat": int(time.time()),
        "role": "authenticated",
    }
    return jwt.encode(claims, secret, algorithm="HS256")
