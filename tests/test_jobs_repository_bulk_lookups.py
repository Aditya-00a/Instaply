import sqlite3
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from backend.db.database import get_connection, init_db  # noqa: E402
from backend.db.jobs_repository import bulk_applied_titles, bulk_company_active_counts  # noqa: E402


def _insert_job(conn: sqlite3.Connection, *, id: str, company: str, title: str, status: str) -> None:
    conn.execute(
        """
        INSERT INTO jobs (id, title, company, url, match_score, status)
        VALUES (?, ?, ?, 'https://example.com/job', 0.9, ?)
        """,
        (id, title, company, status),
    )


def test_bulk_company_active_counts_matches_per_company_count_case_insensitively(tmp_path):
    db_path = init_db(tmp_path / "jobs.db")
    with get_connection(db_path) as conn:
        _insert_job(conn, id="1", company="Acme Corp", title="Engineer", status="applied")
        _insert_job(conn, id="2", company="ACME CORP", title="Designer", status="packet_generated")
        _insert_job(conn, id="3", company="Acme Corp", title="Analyst", status="outreach_sent")
        _insert_job(conn, id="4", company="Acme Corp", title="Intern", status="new")  # not active, excluded
        _insert_job(conn, id="5", company="Other Co", title="PM", status="applied")
        conn.commit()

    counts = bulk_company_active_counts(db_path=db_path)

    assert counts["acme corp"] == 3
    assert counts["other co"] == 1
    assert "nonexistent co" not in counts


def test_bulk_applied_titles_matches_per_pair_lookup_case_insensitively(tmp_path):
    db_path = init_db(tmp_path / "jobs.db")
    with get_connection(db_path) as conn:
        _insert_job(conn, id="1", company="Acme Corp", title="Senior Engineer", status="applied")
        _insert_job(conn, id="2", company="Acme Corp", title="Junior Engineer", status="new")  # not active
        conn.commit()

    applied = bulk_applied_titles(db_path=db_path)

    assert ("acme corp", "senior engineer") in applied
    assert ("acme corp", "junior engineer") not in applied
    assert ("other co", "senior engineer") not in applied


def test_bulk_lookups_are_a_single_connection_regardless_of_catalog_size(tmp_path, monkeypatch):
    db_path = init_db(tmp_path / "jobs.db")
    with get_connection(db_path) as conn:
        for i in range(200):
            _insert_job(conn, id=f"job-{i}", company=f"company{i % 20}", title=f"title{i}", status="applied")
        conn.commit()

    connect_calls = {"count": 0}
    real_connect = sqlite3.connect

    def counting_connect(*args, **kwargs):
        connect_calls["count"] += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting_connect)

    bulk_company_active_counts(db_path=db_path)
    bulk_applied_titles(db_path=db_path)

    # One connection per bulk call — not one per row in the 200-row catalog.
    # This is the regression this test guards: the old per-row helpers opened
    # a fresh connection for every raw job scanned in a discovery cycle
    # (thousands per cycle), which is what made cycles take several extra
    # minutes for no benefit.
    assert connect_calls["count"] == 2


def test_bulk_lookups_scale_sublinearly_with_catalog_size(tmp_path):
    """Smoke test that bulk lookups stay fast as the jobs table grows.

    Not a strict regression gate (CI machines vary), just a sanity check
    that a few thousand rows still resolve in a single fast round trip,
    unlike the old O(raw jobs scanned) connect-per-row pattern.
    """
    db_path = init_db(tmp_path / "jobs.db")
    with get_connection(db_path) as conn:
        for i in range(3000):
            _insert_job(conn, id=f"job-{i}", company=f"company{i % 300}", title=f"title{i}", status="applied")
        conn.commit()

    start = time.perf_counter()
    counts = bulk_company_active_counts(db_path=db_path)
    applied = bulk_applied_titles(db_path=db_path)
    elapsed = time.perf_counter() - start

    assert len(counts) == 300
    assert len(applied) == 3000
    assert elapsed < 2.0
