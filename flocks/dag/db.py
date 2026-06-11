"""
DAG 独立 SQLite 数据库连接管理。

数据库路径: ~/.flocks/dag/dag.db
不与 Flocks Storage 共享连接，零侵入。
"""

import aiosqlite
from pathlib import Path
from typing import Optional

from flocks.utils.log import Log

logger = Log.create(service=__name__)

DATABASE_DIR = Path.home() / ".flocks" / "dag"
DATABASE_PATH = DATABASE_DIR / "dag.db"

_connection: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    """获取 DAG 独立数据库连接（惰性初始化 + 自动建表）"""
    global _connection
    if _connection is None:
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        _connection = await aiosqlite.connect(str(DATABASE_PATH))
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA foreign_keys=ON")
        await _migrate(_connection)
        logger.info("dag.db.connected", {"path": str(DATABASE_PATH)})
    return _connection


async def _migrate(db: aiosqlite.Connection):
    """自动建表（幂等，CREATE TABLE IF NOT EXISTS）"""
    await db.executescript(_SCHEMA)
    await db.commit()
    logger.debug("dag.db.migrated")


async def close_db():
    """关闭数据库连接"""
    global _connection
    if _connection:
        await _connection.close()
        _connection = None
        logger.info("dag.db.closed")


# ============================================================
# SQL Schema
# ============================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dag_projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    origin_fact_id TEXT NOT NULL DEFAULT 'origin',
    goal_fact_id TEXT NOT NULL DEFAULT 'goal',
    max_intents_per_reason INTEGER DEFAULT 3,
    seed_intent_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS dag_facts (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,
    fact_type TEXT DEFAULT 'discovery',
    confidence REAL DEFAULT 1.0,
    evidence TEXT,
    source_intent_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (id, project_id),
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);

CREATE TABLE IF NOT EXISTS dag_intents (
    id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    priority INTEGER DEFAULT 0,
    claimed_by TEXT,
    claimed_at TEXT,
    last_heartbeat_at TEXT,
    concluded_at TEXT,
    result_fact_id TEXT,
    created_by_task TEXT DEFAULT 'reason',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (id, project_id),
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);

CREATE TABLE IF NOT EXISTS dag_intent_sources (
    intent_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    PRIMARY KEY (intent_id, project_id, fact_id),
    FOREIGN KEY (intent_id, project_id) REFERENCES dag_intents(id, project_id),
    FOREIGN KEY (fact_id, project_id) REFERENCES dag_facts(id, project_id)
);

CREATE TABLE IF NOT EXISTS dag_hints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,
    hint_type TEXT DEFAULT 'guidance',
    created_by TEXT,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);

CREATE TABLE IF NOT EXISTS dag_schedule_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    intent_id TEXT,
    session_id TEXT,
    status TEXT DEFAULT 'started',
    rounds INTEGER DEFAULT 0,
    tool_calls_count INTEGER DEFAULT 0,
    result_summary TEXT,
    error_message TEXT,
    duration_seconds REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);
"""
