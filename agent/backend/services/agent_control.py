from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.db.database import get_connection, init_db
from backend.services.config import settings

DB_PATH = init_db(Path(settings.database_path))
GLOBAL_SCOPE = "global"


def _ensure_state_row(scope: str = GLOBAL_SCOPE) -> None:
    with get_connection(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO agent_runtime_state (scope, agent_enabled)
            VALUES (?, 1)
            ON CONFLICT(scope) DO NOTHING
            """,
            (scope,),
        )
        conn.commit()


def get_agent_runtime(scope: str = GLOBAL_SCOPE) -> dict[str, Any]:
    _ensure_state_row(scope)
    with get_connection(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT scope, agent_enabled, updated_at
            FROM agent_runtime_state
            WHERE scope = ?
            LIMIT 1
            """,
            (scope,),
        ).fetchone()
    payload = dict(row) if row else {"scope": scope, "agent_enabled": 1, "updated_at": ""}
    payload["agent_enabled"] = bool(payload.get("agent_enabled", 1))
    payload["status"] = "running" if payload["agent_enabled"] else "stopped"
    return payload


def set_agent_enabled(enabled: bool, scope: str = GLOBAL_SCOPE) -> dict[str, Any]:
    _ensure_state_row(scope)
    with get_connection(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE agent_runtime_state
            SET agent_enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE scope = ?
            """,
            (1 if enabled else 0, scope),
        )
        conn.commit()
    return get_agent_runtime(scope)


def is_agent_enabled(scope: str = GLOBAL_SCOPE) -> bool:
    return bool(get_agent_runtime(scope).get("agent_enabled"))
