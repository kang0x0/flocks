"""
调度决策器 — 决定每个项目下一步做什么任务。
"""

from typing import Optional, List

from flocks.dag.models import (
    ScheduleDecision,
    TaskType,
    IntentEdge,
    GraphSnapshot,
)
from flocks.dag.store import GraphStore
from flocks.utils.log import Log

logger = Log.create(service=__name__)


class Scheduler:
    """两阶段决策：Explore 优先？Reason 优先？"""

    def __init__(self, config: dict):
        self._config = config

    async def decide(
        self, project_id: str, store: GraphStore
    ) -> Optional[ScheduleDecision]:
        """
        决策优先级（每个周期）：
        1. 有 Open Intent → Explore
        2. 有新 Fact / Hint → Reason
        3. 都不满足 → None（跳过）
        """
        snapshot = await store.export_snapshot(project_id)
        if snapshot.status.value != "active":
            return None

        # Priority 1: 有 Open Intent → Explore
        open_intents = await store.get_open_intents(project_id)
        if open_intents:
            intent = self._select_best_intent(open_intents)
            project = await store.get_project(project_id)
            cfg = self._config.get("explore", {})
            return ScheduleDecision(
                project_id=project_id,
                task_type=TaskType.EXPLORE,
                intent_id=intent.id,
                intent_description=intent.description,
                workspace_path=project.get("workspace_path", "/tmp") if project else "/tmp",
                timeout=cfg.get("timeout", 600),
                conclude_timeout=cfg.get("conclude_timeout", 120),
            )

        # Priority 2: 有新信息 → Reason
        if self._has_new_information(snapshot):
            cfg = self._config.get("reason", {})
            return ScheduleDecision(
                project_id=project_id,
                task_type=TaskType.REASON,
                workspace_path="/tmp",
                timeout=cfg.get("timeout", 300),
            )

        return None

    def _select_best_intent(self, intents: List[IntentEdge]) -> IntentEdge:
        """最优 Intent：优先级高 + 来源 Facts 多"""
        return sorted(
            intents,
            key=lambda i: (-i.priority, len(i.source_fact_ids)),
        )[0]

    def _has_new_information(self, snapshot: GraphSnapshot) -> bool:
        """检测是否有新信息需要推理"""
        # 有未读 Hint
        if snapshot.unread_hints:
            return True
        # 有新完成的 Intent（最近一次 Reason 后产出的 Fact）
        # 简化判断：有 Facts 且上次没有 Reason 记录 → 需要 Reason
        if snapshot.statistics.get("total_facts", 0) > 2:
            return True
        return False
