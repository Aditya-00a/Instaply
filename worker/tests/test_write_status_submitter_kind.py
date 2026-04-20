"""Tests for the worker's submitter_kind tagging in `_write_status`,
and structural sanity checks on migration 0014.

We don't connect to Supabase — we mock the supabase-py client just enough
to capture the patch dict and the WHERE filter.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from worker.orchestrator import SUBMITTER_KIND, _write_status


# ─── Tiny fake supabase-py client ────────────────────────────────
class _FakeUpdateChain:
    def __init__(self) -> None:
        self.last_patch: dict | None = None
        self.last_eq: tuple[str, str] | None = None

    def update(self, patch: dict):
        self.last_patch = dict(patch)
        return self

    def eq(self, col: str, val):
        self.last_eq = (col, val)
        return self

    def execute(self):
        return None


class _FakeTableHandle:
    def __init__(self, chain: _FakeUpdateChain) -> None:
        self._chain = chain

    def update(self, patch: dict):
        return self._chain.update(patch)


class _FakeClient:
    def __init__(self) -> None:
        self.chain = _FakeUpdateChain()

    def table(self, name: str):
        assert name == "applications", f"unexpected table: {name}"
        return _FakeTableHandle(self.chain)


# ─── _write_status default tagging ───────────────────────────────
def test_default_writes_submitter_kind_server_instaply():
    db = _FakeClient()
    _write_status(db, "app-1", "submitted")
    patch = db.chain.last_patch
    assert patch is not None
    assert patch["status"] == "submitted"
    assert patch["submitter_kind"] == "server_instaply"
    assert SUBMITTER_KIND == "server_instaply"


def test_explicit_submitter_kind_overrides_default():
    db = _FakeClient()
    _write_status(db, "app-2", "submitted", submitter_kind="extension")
    assert db.chain.last_patch["submitter_kind"] == "extension"


def test_failure_paths_still_carry_submitter_kind():
    """Even on the failed/skipped/needs_review paths the row gets stamped,
    so dashboards counting per-kind don't lose the failure side."""
    for status in ("failed", "skipped", "needs_review"):
        db = _FakeClient()
        _write_status(db, "app-x", status, error_message="something")
        assert db.chain.last_patch["submitter_kind"] == "server_instaply"
        assert db.chain.last_patch["status"] == status
        assert db.chain.last_patch["error_message"] == "something"


# ─── Schema-drift safety: only known columns make it into the patch ──
_LIVE_APPLICATIONS_COLUMNS = {
    # Verified against supabase/migrations/0001_init.sql + 0014.
    "status",
    "submission_log",
    "screenshot_url",
    "confirmation_email_id",
    "confirmed_at",
    "error_message",
    "completed_at",
    "submitter_kind",
}


def test_full_optional_payload_only_writes_known_columns():
    db = _FakeClient()
    _write_status(
        db,
        "app-3",
        "confirmed",
        submission_log={"stage": "submitted"},
        screenshot_url="https://example.test/s.png",
        confirmation_email_id="msg-abc",
        confirmed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        error_message=None,        # None → not written
        completed=True,
    )
    written = set(db.chain.last_patch.keys())
    # Every key written must be a real applications column.
    unknown = written - _LIVE_APPLICATIONS_COLUMNS
    assert not unknown, f"_write_status wrote unknown columns: {unknown}"
    # And all the truthy fields landed.
    expected_present = {
        "status", "submission_log", "screenshot_url",
        "confirmation_email_id", "confirmed_at", "completed_at",
        "submitter_kind",
    }
    assert expected_present.issubset(written)
    # error_message=None must NOT be written.
    assert "error_message" not in db.chain.last_patch


def test_eq_filter_targets_application_id():
    db = _FakeClient()
    _write_status(db, "abc-123", "queued")
    assert db.chain.last_eq == ("id", "abc-123")


# ─── Migration 0014 structural checks ────────────────────────────
_MIG_PATH = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0014_applications_submitter_kind.sql"


def test_migration_0014_exists():
    assert _MIG_PATH.exists(), f"migration not found: {_MIG_PATH}"


def test_migration_0014_adds_column_with_safe_default():
    sql = _MIG_PATH.read_text()
    # Column add is idempotent
    assert re.search(r"add column if not exists submitter_kind", sql, re.I)
    # Existing rows backfill to server_revize (legacy submitter path)
    assert "default 'server_revize'" in sql
    # NOT NULL — never a null tag
    assert re.search(r"submitter_kind\s+text\s+not\s+null", sql, re.I)


def test_migration_0014_check_constraint_lists_all_known_kinds():
    sql = _MIG_PATH.read_text()
    # Allow-list must include every value the worker / dashboards know about.
    for kind in ("server_revize", "server_instaply", "extension", "manual"):
        assert f"'{kind}'" in sql, f"submitter_kind allow-list missing {kind!r}"


def test_migration_0014_creates_telemetry_index():
    sql = _MIG_PATH.read_text()
    # (submitter_kind, status) index for per-kind success-rate queries.
    assert "create index if not exists applications_submitter_kind_status_idx" in sql
    assert "(submitter_kind, status)" in sql
