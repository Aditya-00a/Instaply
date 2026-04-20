"""Tests for the canary feature flag + worker claim filter.

Two surfaces:
  - migration 0015 file shape
  - `_opted_in_user_ids` cache + `_claim_one` short-circuits when no
    users are opted in (no DB UPDATE happens)
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from worker import orchestrator as orch


# ─── Migration 0015 structural checks ────────────────────────────
_MIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "0015_preferences_use_native_worker.sql"
)


def test_migration_0015_exists():
    assert _MIG_PATH.exists(), f"missing migration: {_MIG_PATH}"


def test_migration_0015_adds_flag_with_safe_default():
    sql = _MIG_PATH.read_text()
    assert re.search(
        r"add\s+column\s+if\s+not\s+exists\s+use_native_worker\s+boolean\s+not\s+null\s+default\s+false",
        sql,
        re.I,
    ), "use_native_worker must be added as boolean NOT NULL DEFAULT false"


def test_migration_0015_creates_partial_index_on_true_side():
    sql = _MIG_PATH.read_text()
    assert "preferences_use_native_worker_true_idx" in sql
    assert re.search(r"where\s+use_native_worker\s*=\s*true", sql, re.I), \
        "partial index must filter to TRUE rows only"


# ─── Fake supabase-py: minimal select chain ──────────────────────
class _FakeSelectChain:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def execute(self):
        class _Resp:
            pass
        r = _Resp()
        r.data = self._data
        return r


class _FakeClient:
    def __init__(self, opted_in_rows: list[dict] | None = None, *, raise_on_select: bool = False):
        self._opted_in_rows = opted_in_rows if opted_in_rows is not None else []
        self._raise_on_select = raise_on_select
        self.update_call_count = 0
        self.select_call_count = 0

    # Used by _opted_in_user_ids
    def table(self, name: str):
        if name == "preferences":
            self.select_call_count += 1
            if self._raise_on_select:
                raise RuntimeError("transient supabase failure")
            return _FakeSelectChain(self._opted_in_rows)
        if name == "applications":
            self.update_call_count += 1
            # We never get here in the no-opted-in path; if we do the test fails.
            return _FakeSelectChain([])
        raise AssertionError(f"unexpected table: {name}")


def _reset_cache():
    orch._OPTED_IN_CACHE["ids"] = []
    orch._OPTED_IN_CACHE["ts"] = 0.0


# ─── _opted_in_user_ids cache behavior ───────────────────────────
def test_opted_in_user_ids_returns_empty_when_no_one_opted_in():
    _reset_cache()
    db = _FakeClient(opted_in_rows=[])
    assert orch._opted_in_user_ids(db) == []
    assert db.select_call_count == 1


def test_opted_in_user_ids_unwraps_user_id_field():
    _reset_cache()
    db = _FakeClient(opted_in_rows=[{"user_id": "u1"}, {"user_id": "u2"}])
    assert orch._opted_in_user_ids(db) == ["u1", "u2"]


def test_opted_in_user_ids_caches_and_serves_from_cache():
    _reset_cache()
    db = _FakeClient(opted_in_rows=[{"user_id": "u1"}])
    a = orch._opted_in_user_ids(db)
    b = orch._opted_in_user_ids(db)
    assert a == b == ["u1"]
    assert db.select_call_count == 1, "second call must hit the cache, not the DB"


def test_opted_in_user_ids_force_refresh_reissues_query():
    _reset_cache()
    db = _FakeClient(opted_in_rows=[{"user_id": "u1"}])
    orch._opted_in_user_ids(db)
    orch._opted_in_user_ids(db, force_refresh=True)
    assert db.select_call_count == 2


def test_opted_in_user_ids_fail_closed_returns_last_cache_on_error():
    """A transient lookup error must NOT silently freeze the worker by
    returning [] — return the last good cache instead."""
    _reset_cache()
    # Seed cache with one good fetch
    good = _FakeClient(opted_in_rows=[{"user_id": "u1"}])
    orch._opted_in_user_ids(good)
    # Now simulate a transient outage on a forced refresh
    bad = _FakeClient(raise_on_select=True)
    result = orch._opted_in_user_ids(bad, force_refresh=True)
    assert result == ["u1"], "must return the LAST cached value on error"


# ─── _claim_one short-circuits when no users opted in ────────────
def test_claim_one_returns_none_and_skips_update_when_no_opted_in_users():
    _reset_cache()
    db = _FakeClient(opted_in_rows=[])
    result = orch._claim_one(db)
    assert result is None
    # Crucially, the applications table was never touched. This is the
    # "zero-risk" property that lets us deploy the worker before any
    # canary user exists.
    assert db.update_call_count == 0
    assert db.select_call_count == 1   # only the preferences lookup


def test_claim_one_returns_none_on_module_constant_default():
    """Sanity: SUBMITTER_KIND constant unchanged by today's task."""
    assert orch.SUBMITTER_KIND == "server_instaply"
