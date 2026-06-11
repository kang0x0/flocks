"""
Graph Store — Fact / Intent / Hint 持久化 CRUD。

基于独立 dag.db（aiosqlite），不依赖 Flocks Storage。
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from flocks.dag.db import get_db
from flocks.dag.models import (
    DagProject,
    FactNode,
    IntentEdge,
    Hint,
    ScheduleLog,
    GraphSnapshot,
    ProjectStatus,
    IntentStatus,
    FactType,
)
from flocks.utils.log import Log

logger = Log.create(service=__name__)


class GraphStore:
    """Fact-Intent 图持久化存储"""

    # ================================================================
    # Projects
    # ================================================================

    @staticmethod
    async def create_project(
        title: str,
        origin_content: str,
        goal_content: str,
        description: str = "",
    ) -> str:
        """创建探索项目并写入 origin/goal Facts + seed_intent"""
        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        now = _now()

        db = await get_db()
        await db.execute(
            """INSERT INTO dag_projects (id, title, description, status,
               origin_fact_id, goal_fact_id, max_intents_per_reason, created_at, updated_at)
               VALUES (?, ?, ?, 'active', 'origin', 'goal', 3, ?, ?)""",
            (project_id, title, description, now, now),
        )
        await db.commit()

        # origin fact
        await GraphStore.add_fact(FactNode(
            id="origin", project_id=project_id,
            content=origin_content, fact_type=FactType.ORIGIN.value,
        ))
        # goal fact
        await GraphStore.add_fact(FactNode(
            id="goal", project_id=project_id,
            content=goal_content, fact_type=FactType.GOAL.value,
        ))
        # seed intent
        seed = IntentEdge(
            id="i_seed",
            project_id=project_id,
            description=f"初始探索：{goal_content[:80]}...",
            source_fact_ids=["origin"],
            priority=0,
            created_by_task="seed",
        )
        await GraphStore.create_intent(seed)
        await db.execute(
            "UPDATE dag_projects SET seed_intent_id = ? WHERE id = ?",
            ("i_seed", project_id),
        )
        await db.commit()

        logger.info("dag.project.created", {"project_id": project_id, "title": title})
        return project_id

    @staticmethod
    async def get_project(project_id: str) -> Optional[dict]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_projects WHERE id = ?", (project_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    async def list_active_projects() -> List[dict]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_projects WHERE status = 'active' ORDER BY created_at DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    @staticmethod
    async def list_projects(status: Optional[str] = None) -> List[dict]:
        db = await get_db()
        if status:
            cursor = await db.execute(
                "SELECT * FROM dag_projects WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM dag_projects ORDER BY created_at DESC"
            )
        return [dict(row) for row in await cursor.fetchall()]

    @staticmethod
    async def update_status(project_id: str, status: ProjectStatus):
        db = await get_db()
        now = _now()
        if status == ProjectStatus.COMPLETED:
            await db.execute(
                "UPDATE dag_projects SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?",
                (status.value, now, now, project_id),
            )
        else:
            await db.execute(
                "UPDATE dag_projects SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, project_id),
            )
        await db.commit()
        logger.info("dag.project.status_updated", {"project_id": project_id, "status": status.value})

    # ================================================================
    # Facts
    # ================================================================

    @staticmethod
    async def add_fact(fact: FactNode) -> FactNode:
        db = await get_db()
        await db.execute(
            """INSERT OR REPLACE INTO dag_facts
               (id, project_id, content, fact_type, confidence, evidence, source_intent_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fact.id, fact.project_id, fact.content, fact.fact_type,
                fact.confidence, fact.evidence, fact.source_intent_id, _now(),
            ),
        )
        await db.commit()
        return fact

    @staticmethod
    async def get_facts(project_id: str) -> List[FactNode]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_facts WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        )
        return [_row_to_fact(row) for row in await cursor.fetchall()]

    @staticmethod
    async def get_fact(project_id: str, fact_id: str) -> Optional[FactNode]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_facts WHERE project_id = ? AND id = ?",
            (project_id, fact_id),
        )
        row = await cursor.fetchone()
        return _row_to_fact(row) if row else None

    @staticmethod
    async def get_origin_fact(project_id: str) -> Optional[FactNode]:
        return await GraphStore.get_fact(project_id, "origin")

    @staticmethod
    async def get_goal_fact(project_id: str) -> Optional[FactNode]:
        return await GraphStore.get_fact(project_id, "goal")

    # ================================================================
    # Intents
    # ================================================================

    @staticmethod
    async def create_intent(intent: IntentEdge) -> IntentEdge:
        db = await get_db()
        await db.execute(
            """INSERT OR REPLACE INTO dag_intents
               (id, project_id, description, status, priority, created_by_task, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                intent.id, intent.project_id, intent.description,
                intent.status.value, intent.priority,
                intent.created_by_task, _now(),
            ),
        )
        # 写入 source_fact_ids
        for src_id in intent.source_fact_ids:
            await db.execute(
                "INSERT OR IGNORE INTO dag_intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                (intent.id, intent.project_id, src_id),
            )
        await db.commit()
        return intent

    @staticmethod
    async def claim_intent(project_id: str, intent_id: str) -> bool:
        db = await get_db()
        cursor = await db.execute(
            "UPDATE dag_intents SET status = 'claimed', claimed_at = ? WHERE project_id = ? AND id = ? AND status = 'open'",
            (_now(), project_id, intent_id),
        )
        await db.commit()
        return cursor.rowcount > 0

    @staticmethod
    async def conclude_intent(
        project_id: str, intent_id: str, result_fact: FactNode
    ) -> bool:
        db = await get_db()
        # 写入结果 Fact
        await GraphStore.add_fact(result_fact)
        # 更新 Intent 状态
        cursor = await db.execute(
            """UPDATE dag_intents
               SET status = 'completed', concluded_at = ?, result_fact_id = ?
               WHERE project_id = ? AND id = ?""",
            (_now(), result_fact.id, project_id, intent_id),
        )
        await db.commit()
        return cursor.rowcount > 0

    @staticmethod
    async def heartbeat_intent(project_id: str, intent_id: str) -> bool:
        db = await get_db()
        cursor = await db.execute(
            "UPDATE dag_intents SET last_heartbeat_at = ? WHERE project_id = ? AND id = ?",
            (_now(), project_id, intent_id),
        )
        await db.commit()
        return cursor.rowcount > 0

    @staticmethod
    async def get_open_intents(project_id: str) -> List[IntentEdge]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_intents WHERE project_id = ? AND status = 'open' ORDER BY priority ASC, created_at ASC",
            (project_id,),
        )
        intents = []
        for row in await cursor.fetchall():
            intent = _row_to_intent(row)
            intent.source_fact_ids = await GraphStore._get_intent_sources(
                project_id, intent.id
            )
            intents.append(intent)
        return intents

    @staticmethod
    async def get_intents(project_id: str) -> List[IntentEdge]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_intents WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        )
        intents = []
        for row in await cursor.fetchall():
            intent = _row_to_intent(row)
            intent.source_fact_ids = await GraphStore._get_intent_sources(
                project_id, intent.id
            )
            intents.append(intent)
        return intents

    @staticmethod
    async def release_stale_intents(max_heartbeat_age_seconds: int):
        """释放心跳超时的 Intent（回退为 open）"""
        db = await get_db()
        threshold = _now_ago(max_heartbeat_age_seconds)
        await db.execute(
            """UPDATE dag_intents
               SET status = 'open', claimed_by = NULL, claimed_at = NULL
               WHERE status = 'claimed'
               AND (last_heartbeat_at IS NULL OR last_heartbeat_at < ?)""",
            (threshold,),
        )
        await db.commit()

    @staticmethod
    async def _get_intent_sources(project_id: str, intent_id: str) -> List[str]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT fact_id FROM dag_intent_sources WHERE project_id = ? AND intent_id = ?",
            (project_id, intent_id),
        )
        return [row["fact_id"] for row in await cursor.fetchall()]

    # ================================================================
    # Hints
    # ================================================================

    @staticmethod
    async def add_hint(
        project_id: str, content: str, hint_type: str = "guidance", created_by: str = "operator"
    ) -> str:
        hint_id = f"h_{uuid.uuid4().hex[:8]}"
        db = await get_db()
        await db.execute(
            "INSERT INTO dag_hints (id, project_id, content, hint_type, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (hint_id, project_id, content, hint_type, created_by, _now()),
        )
        await db.commit()
        return hint_id

    @staticmethod
    async def mark_hints_read(project_id: str):
        db = await get_db()
        await db.execute(
            "UPDATE dag_hints SET is_read = 1 WHERE project_id = ?", (project_id,)
        )
        await db.commit()

    @staticmethod
    async def get_unread_hints(project_id: str) -> List[dict]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_hints WHERE project_id = ? AND is_read = 0 ORDER BY created_at",
            (project_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    # ================================================================
    # Graph
    # ================================================================

    @staticmethod
    async def export_snapshot(project_id: str) -> GraphSnapshot:
        project = await GraphStore.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        facts = await GraphStore.get_facts(project_id)
        intents = await GraphStore.get_intents(project_id)
        open_intents = [i for i in intents if i.status == IntentStatus.OPEN]
        unread_hints = [
            h["content"] for h in await GraphStore.get_unread_hints(project_id)
        ]

        origin_fact = next((f for f in facts if f.id == "origin"), None)
        goal_fact = next((f for f in facts if f.id == "goal"), None)

        total_intents = len(intents)
        completed_intents = sum(1 for i in intents if i.status == IntentStatus.COMPLETED)

        return GraphSnapshot(
            project_id=project_id,
            project_title=project["title"],
            status=ProjectStatus(project["status"]),
            origin_fact=origin_fact,
            goal_fact=goal_fact,
            facts=facts,
            open_intents=open_intents,
            all_intents=intents,
            unread_hints=unread_hints,
            statistics={
                "total_facts": len(facts),
                "total_intents": total_intents,
                "open_intents": len(open_intents),
                "completed_intents": completed_intents,
                "unread_hints": len(unread_hints),
            },
        )

    @staticmethod
    async def get_statistics(project_id: str) -> dict:
        snapshot = await GraphStore.export_snapshot(project_id)
        return snapshot.statistics

    # ================================================================
    # Schedule Log
    # ================================================================

    @staticmethod
    async def log_task_start(
        project_id: str, task_type: str, intent_id: Optional[str], session_id: str
    ) -> int:
        db = await get_db()
        cursor = await db.execute(
            """INSERT INTO dag_schedule_log
               (project_id, task_type, intent_id, session_id, status, created_at)
               VALUES (?, ?, ?, ?, 'started', ?)""",
            (project_id, task_type, intent_id, session_id, _now()),
        )
        await db.commit()
        return cursor.lastrowid

    @staticmethod
    async def log_task_complete(
        log_id: int,
        status: str,
        rounds: int,
        tool_calls_count: int,
        result_summary: str,
        duration_seconds: float,
    ):
        db = await get_db()
        await db.execute(
            """UPDATE dag_schedule_log
               SET status = ?, rounds = ?, tool_calls_count = ?,
                   result_summary = ?, duration_seconds = ?
               WHERE id = ?""",
            (status, rounds, tool_calls_count, result_summary, duration_seconds, log_id),
        )
        await db.commit()

    @staticmethod
    async def get_task_log(log_id: int) -> Optional[dict]:
        db = await get_db()
        cursor = await db.execute(
            "SELECT * FROM dag_schedule_log WHERE id = ?", (int(log_id),)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    async def list_task_logs(project_id: str, limit: int = 50) -> List[dict]:
        db = await get_db()
        cursor = await db.execute(
            """SELECT * FROM dag_schedule_log
               WHERE project_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]


# ================================================================
# Internal helpers
# ================================================================

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ago(seconds: int) -> str:
    from datetime import timedelta
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_fact(row) -> FactNode:
    return FactNode(
        id=row["id"],
        project_id=row["project_id"],
        content=row["content"],
        fact_type=row["fact_type"],
        confidence=row["confidence"],
        evidence=row.get("evidence"),
        source_intent_id=row.get("source_intent_id"),
    )


def _row_to_intent(row) -> IntentEdge:
    return IntentEdge(
        id=row["id"],
        project_id=row["project_id"],
        description=row["description"],
        status=IntentStatus(row["status"]),
        priority=row["priority"] or 0,
        claimed_by=row.get("claimed_by"),
        result_fact_id=row.get("result_fact_id"),
        created_by_task=row.get("created_by_task", "reason"),
    )
