"""Cairn SQLite storage layer.

Merged from original Cairn's db.py + services.py.
Database path: ~/.flocks/cairn.db
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from fastapi import HTTPException

from flocks.cairn.models import Intent, ProjectMeta, ProjectReason, Fact, Hint

DEFAULT_DB = Path.home() / ".flocks" / "cairn.db"

_db_path: Path | None = None

# Maximum retries for database locked errors
_MAX_RETRIES = 3
_RETRY_DELAY_MS = 200

SCHEMA = """\
CREATE TABLE IF NOT EXISTS settings (
    intent_timeout INTEGER NOT NULL DEFAULT 300,
    reason_timeout INTEGER NOT NULL DEFAULT 300
);

INSERT OR IGNORE INTO settings (rowid, intent_timeout, reason_timeout) VALUES (1, 300, 300);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    reason_worker TEXT,
    reason_trigger TEXT,
    reason_started_at TEXT,
    reason_last_heartbeat_at TEXT
);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS intents (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    to_fact_id TEXT,
    description TEXT NOT NULL,
    creator TEXT NOT NULL,
    worker TEXT,
    last_heartbeat_at TEXT,
    created_at TEXT NOT NULL,
    concluded_at TEXT,
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS intent_sources (
    intent_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    PRIMARY KEY (intent_id, project_id, fact_id),
    FOREIGN KEY (intent_id, project_id) REFERENCES intents(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS hints (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    creator TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (id, project_id)
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO counters (name, value) VALUES ('project', 0);

CREATE TABLE IF NOT EXISTS scoped_counters (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, kind)
);

CREATE TABLE IF NOT EXISTS worker_session_logs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    intent_id TEXT,
    session_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    worker TEXT NOT NULL,
    prompt_preview TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'success',
    created_at TEXT NOT NULL,
    FOREIGN KEY (intent_id, project_id) REFERENCES intents(id, project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS worker_session_facts (
    log_id TEXT NOT NULL REFERENCES worker_session_logs(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    fact_id TEXT NOT NULL,
    PRIMARY KEY (log_id, project_id, fact_id),
    FOREIGN KEY (fact_id, project_id) REFERENCES facts(id, project_id) ON DELETE CASCADE
);
"""


def configure(path: Path = DEFAULT_DB) -> None:
    global _db_path
    if _db_path is not None:
        return
    _db_path = path
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript("PRAGMA journal_mode=WAL")
        conn.executescript("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)


def _connect_with_retry(db_path: str, timeout: int = 10) -> sqlite3.Connection:
    last_error = None
    for attempt in range(_MAX_RETRIES):
        try:
            conn = sqlite3.connect(db_path, timeout=timeout)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.OperationalError as e:
            last_error = e
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY_MS / 1000)
    raise HTTPException(500, f"Cannot open database: {last_error}")


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    if _db_path is None:
        configure()
    conn = _connect_with_retry(str(_db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Database error: {e}") from e
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def next_project_id(conn: sqlite3.Connection) -> str:
    conn.execute("UPDATE counters SET value = value + 1 WHERE name = 'project'")
    row = conn.execute("SELECT value FROM counters WHERE name = 'project'").fetchone()
    return f"proj_{row['value']:03d}"


def _next_scoped_id(
    conn: sqlite3.Connection, kind: str, prefix: str, project_id: str
) -> str:
    conn.execute(
        "INSERT OR IGNORE INTO scoped_counters (project_id, kind, value) VALUES (?, ?, 0)",
        (project_id, kind),
    )
    conn.execute(
        "UPDATE scoped_counters SET value = value + 1 WHERE project_id = ? AND kind = ?",
        (project_id, kind),
    )
    row = conn.execute(
        "SELECT value FROM scoped_counters WHERE project_id = ? AND kind = ?",
        (project_id, kind),
    ).fetchone()
    assert row is not None
    return f"{prefix}{row['value']:03d}"


def next_fact_id(conn: sqlite3.Connection, project_id: str) -> str:
    return _next_scoped_id(conn, "fact", "f", project_id)


def next_intent_id(conn: sqlite3.Connection, project_id: str) -> str:
    return _next_scoped_id(conn, "intent", "i", project_id)


def next_hint_id(conn: sqlite3.Connection, project_id: str) -> str:
    return _next_scoped_id(conn, "hint", "h", project_id)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def get_project_or_404(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Project not found")
    return row


def check_project_active(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = get_project_or_404(conn, project_id)
    if row["status"] != "active":
        raise HTTPException(403, f"Project is {row['status']}")
    return row


def check_project_hint_writable(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = get_project_or_404(conn, project_id)
    if row["status"] not in ("active", "stopped", "completed"):
        raise HTTPException(403, f"Project is {row['status']}")
    return row


def check_project_completed(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = get_project_or_404(conn, project_id)
    if row["status"] != "completed":
        raise HTTPException(403, f"Project is {row['status']}")
    return row


def validate_facts_exist(
    conn: sqlite3.Connection, project_id: str, fact_ids: list[str]
) -> None:
    for fid in fact_ids:
        row = conn.execute(
            "SELECT 1 FROM facts WHERE id = ? AND project_id = ?", (fid, project_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Fact {fid} not found")


def validate_goal_not_in_sources(fact_ids: list[str]) -> None:
    if "goal" in fact_ids:
        raise HTTPException(400, "goal cannot be used in from")


def validate_intent_creator_worker(creator: str, worker: str | None) -> None:
    if worker is not None and worker != creator:
        raise HTTPException(400, "worker must be null or equal to creator")


# ---------------------------------------------------------------------------
# Intent helpers
# ---------------------------------------------------------------------------

def get_intent_or_404(
    conn: sqlite3.Connection, project_id: str, intent_id: str
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM intents WHERE id = ? AND project_id = ?",
        (intent_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Intent not found")
    return row


def get_claimable_open_intent_or_404(
    conn: sqlite3.Connection, project_id: str, intent_id: str, worker: str
) -> sqlite3.Row:
    expire_workers(conn, project_id)
    row = get_intent_or_404(conn, project_id, intent_id)
    if row["to_fact_id"] is not None:
        raise HTTPException(409, "Intent already concluded")
    if row["worker"] is not None and row["worker"] != worker:
        raise HTTPException(409, f"Intent is currently claimed by {row['worker']}")
    return row


def get_releasable_open_intent_or_404(
    conn: sqlite3.Connection, project_id: str, intent_id: str, worker: str
) -> sqlite3.Row:
    expire_workers(conn, project_id)
    row = get_intent_or_404(conn, project_id, intent_id)
    if row["to_fact_id"] is not None:
        raise HTTPException(409, "Intent already concluded")
    if row["worker"] is None:
        return row
    if row["worker"] != worker:
        raise HTTPException(409, f"Intent is currently claimed by {row['worker']}")
    return row


def get_completion_intent_or_409(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    rows = conn.execute(
        "SELECT * FROM intents WHERE project_id = ? AND to_fact_id = 'goal'",
        (project_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(409, "Completed project is missing its completion intent")
    if len(rows) != 1:
        raise HTTPException(409, "Completed project has multiple completion intents")
    return rows[0]


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------

def intent_to_model(conn: sqlite3.Connection, row: sqlite3.Row, project_id: str) -> Intent:
    sources = conn.execute(
        "SELECT fact_id FROM intent_sources WHERE intent_id = ? AND project_id = ? ORDER BY rowid",
        (row["id"], project_id),
    ).fetchall()
    return Intent(
        id=row["id"],
        **{"from": [s["fact_id"] for s in sources]},
        to=row["to_fact_id"],
        description=row["description"],
        creator=row["creator"],
        worker=row["worker"],
        last_heartbeat_at=row["last_heartbeat_at"],
        created_at=row["created_at"],
        concluded_at=row["concluded_at"],
    )


def build_intents(conn: sqlite3.Connection, project_id: str) -> list[Intent]:
    rows = conn.execute(
        "SELECT * FROM intents WHERE project_id = ? ORDER BY created_at",
        (project_id,),
    ).fetchall()
    return [intent_to_model(conn, r, project_id) for r in rows]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_intent_timeout(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT intent_timeout FROM settings WHERE rowid = 1").fetchone()
    return row["intent_timeout"]


def get_reason_timeout(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT reason_timeout FROM settings WHERE rowid = 1").fetchone()
    return row["reason_timeout"]


# ---------------------------------------------------------------------------
# Project reason helpers
# ---------------------------------------------------------------------------

def project_reason_from_row(row: sqlite3.Row) -> ProjectReason | None:
    if row["reason_worker"] is None:
        return None
    return ProjectReason(
        worker=row["reason_worker"],
        trigger=row["reason_trigger"],
        started_at=row["reason_started_at"],
        last_heartbeat_at=row["reason_last_heartbeat_at"],
    )


def project_meta_from_row(row: sqlite3.Row) -> ProjectMeta:
    return ProjectMeta(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        reason=project_reason_from_row(row),
    )


def clear_project_reason(conn: sqlite3.Connection, project_id: str) -> None:
    conn.execute(
        """
        UPDATE projects
        SET reason_worker = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE id = ?
        """,
        (project_id,),
    )


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def expire_workers(conn: sqlite3.Connection, project_id: str | None = None) -> None:
    timeout = get_intent_timeout(conn)
    now = utcnow()
    query = """
        UPDATE intents
        SET worker = NULL
        WHERE to_fact_id IS NULL
          AND worker IS NOT NULL
          AND last_heartbeat_at IS NOT NULL
          AND (julianday(?) - julianday(last_heartbeat_at)) * 86400 > ?
    """
    params: tuple = (now, timeout)
    if project_id is not None:
        query = query.replace("WHERE ", "WHERE project_id = ? AND ", 1)
        params = (project_id, now, timeout)
    conn.execute(query, params)


def expire_reason_leases(conn: sqlite3.Connection, project_id: str | None = None) -> None:
    timeout = get_reason_timeout(conn)
    now = utcnow()
    query = """
        UPDATE projects
        SET reason_worker = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE reason_worker IS NOT NULL
          AND reason_last_heartbeat_at IS NOT NULL
          AND (julianday(?) - julianday(reason_last_heartbeat_at)) * 86400 > ?
    """
    params: tuple = (now, timeout)
    if project_id is not None:
        query = query.replace("WHERE ", "WHERE id = ? AND ", 1)
        params = (project_id, now, timeout)
    conn.execute(query, params)


# ---------------------------------------------------------------------------
# Project-level queries exposed for routes
# ---------------------------------------------------------------------------

def get_settings(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute("SELECT intent_timeout, reason_timeout FROM settings WHERE rowid = 1").fetchone()
    return {"intent_timeout": row["intent_timeout"], "reason_timeout": row["reason_timeout"]}


def update_settings(conn: sqlite3.Connection, intent_timeout: int, reason_timeout: int) -> None:
    conn.execute(
        "UPDATE settings SET intent_timeout = ?, reason_timeout = ? WHERE rowid = 1",
        (intent_timeout, reason_timeout),
    )


# ---------------------------------------------------------------------------
# Worker Session Logs
# ---------------------------------------------------------------------------

def create_session_log(
    conn: sqlite3.Connection,
    project_id: str,
    session_id: str,
    phase: str,
    worker: str,
    *,
    intent_id: str | None = None,
    prompt_preview: str = "",
    status: str = "success",
) -> str:
    import uuid
    log_id = f"sl_{uuid.uuid4().hex[:12]}"
    now = utcnow()
    conn.execute(
        """INSERT INTO worker_session_logs
           (id, project_id, intent_id, session_id, phase, worker, prompt_preview, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (log_id, project_id, intent_id, session_id, phase, worker, prompt_preview, status, now),
    )
    return log_id


def link_session_facts(
    conn: sqlite3.Connection,
    log_id: str,
    project_id: str,
    fact_ids: list[str],
) -> None:
    for fid in fact_ids:
        conn.execute(
            "INSERT OR IGNORE INTO worker_session_facts (log_id, project_id, fact_id) VALUES (?, ?, ?)",
            (log_id, project_id, fid),
        )


def list_session_logs(
    conn: sqlite3.Connection,
    project_id: str,
) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM worker_session_logs
           WHERE project_id = ?
           ORDER BY created_at""",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_session_logs_by_intent(
    conn: sqlite3.Connection,
    project_id: str,
    intent_id: str,
) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM worker_session_logs
           WHERE project_id = ? AND intent_id = ?
           ORDER BY created_at""",
        (project_id, intent_id),
    ).fetchall()
    return [dict(r) for r in rows]


def list_session_logs_by_fact(
    conn: sqlite3.Connection,
    project_id: str,
    fact_id: str,
) -> list[dict]:
    rows = conn.execute(
        """SELECT l.* FROM worker_session_logs l
           JOIN worker_session_facts f ON f.log_id = l.id
           WHERE l.project_id = ? AND f.fact_id = ?
           ORDER BY l.created_at""",
        (project_id, fact_id),
    ).fetchall()
    return [dict(r) for r in rows]


def list_session_ids_for_project(
    conn: sqlite3.Connection,
    project_id: str,
) -> list[str]:
    """Return all Flocks session IDs associated with a project."""
    rows = conn.execute(
        "SELECT DISTINCT session_id FROM worker_session_logs WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    return [r["session_id"] for r in rows]