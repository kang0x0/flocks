"""
DAG Orchestrator 主调度循环。

自管理 asyncio 循环，不依赖 Flocks TaskManager。
"""

import asyncio
from typing import Dict

from flocks.dag.store import GraphStore
from flocks.dag.models import (
    ScheduleDecision,
    TaskType,
    FactNode,
    IntentEdge,
)
from flocks.dag.orchestrator.scheduler import Scheduler
from flocks.dag.orchestrator.heartbeat import HeartbeatManager
from flocks.dag.orchestrator.tasks.reason import execute_reason
from flocks.dag.orchestrator.tasks.explore import execute_explore
from flocks.dag.events import DagTaskStarted, DagTaskCompleted, GraphStateChanged
from flocks.bus import Bus
from flocks.utils.log import Log

logger = Log.create(service=__name__)


class DagOrchestrator:
    """DAG 编排器主循环

    使用自管理的 asyncio 循环，可配置间隔（默认 5 秒）。
    """

    def __init__(
        self,
        graph_store: GraphStore,
        session_manager,
        config: dict,
        bus: Bus = None,
    ):
        self._store = graph_store
        self._session_manager = session_manager
        self._config = config
        self._bus = bus
        self._scheduler = Scheduler(config)
        self._heartbeat_mgr = HeartbeatManager(
            graph_store,
            interval=config.get("schedule", {}).get("heartbeat_interval", 10),
        )
        self._running = False
        self._running_tasks: Dict[str, int] = {}  # project_id -> active count
        self._schedule_interval = config.get("schedule", {}).get("interval", 5)
        self._max_project_concurrency = config.get("concurrency", {}).get("max_project", 4)
        self._max_explore_concurrency = config.get("concurrency", {}).get("max_explore", 3)

    async def start(self):
        """启动调度循环"""
        logger.info("orchestrator.starting", {"interval": self._schedule_interval})
        self._running = True
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.error("orchestrator.tick_error", {"error": str(e)})
            await asyncio.sleep(self._schedule_interval)

    async def stop(self):
        """停止调度循环"""
        logger.info("orchestrator.stopping")
        self._running = False

    async def tick(self):
        """单个调度周期"""
        # 1. 获取 active 项目
        active_projects = await self._store.list_active_projects()
        if not active_projects:
            return

        # 2. 释放僵尸 Intent
        hb_timeout = self._config.get("schedule", {}).get("heartbeat_interval", 10) * 3
        await self._store.release_stale_intents(hb_timeout)

        # 3. 逐项目调度决策
        for project in active_projects:
            pid = project["id"]
            if self._is_project_at_capacity(pid):
                continue
            decision = await self._scheduler.decide(pid, self._store)
            if decision:
                self._running_tasks[pid] = self._running_tasks.get(pid, 0) + 1
                asyncio.create_task(self._dispatch(decision), name=f"dag-{pid}")

    async def _dispatch(self, decision: ScheduleDecision):
        """派发 → 创建 Session → ReAct → 校验 → 写回"""
        pid = decision.project_id
        try:
            snapshot = await self._store.export_snapshot(pid)
            goal_fact = snapshot.goal_fact
            goal_content = goal_fact.content if goal_fact else "完成探索目标"
            project = await self._store.get_project(pid)
            max_intents = project.get("max_intents_per_reason", 3) if project else 3

            if decision.task_type == TaskType.REASON:
                await self._do_reason(decision, snapshot, goal_content, max_intents)
            elif decision.task_type == TaskType.EXPLORE:
                await self._do_explore(decision, snapshot, goal_content)
        except Exception as e:
            logger.error("dispatch.error", {
                "project_id": pid,
                "task_type": decision.task_type.value,
                "error": str(e),
            })
        finally:
            self._running_tasks[pid] = max(0, self._running_tasks.get(pid, 1) - 1)

    async def _do_reason(self, decision, snapshot, goal_content, max_intents):
        """执行 Reason 任务 → 产出 Intent(s) 或声明完成"""
        output = await execute_reason(
            self._session_manager,
            snapshot,
            goal_content,
            max_intents,
            self._config.get("tasks", {}),
            decision.workspace_path,
        )

        if output.complete:
            await self._store.update_status(decision.project_id, "completed")
            logger.info("project.completed", {"project_id": decision.project_id})
            return

        # 写入新 Intent
        for i, intent_data in enumerate(output.new_intents):
            intent_id = f"i_{decision.project_id}_{i}_{_ts_short()}"
            intent = IntentEdge(
                id=intent_id,
                project_id=decision.project_id,
                description=intent_data.get("description", ""),
                source_fact_ids=intent_data.get("source_fact_ids", []),
                priority=intent_data.get("priority", 0),
                created_by_task="reason",
            )
            await self._store.create_intent(intent)

        # 标记 Hint 已读
        await self._store.mark_hints_read(decision.project_id)

    async def _do_explore(self, decision, snapshot, goal_content):
        """执行 Explore 任务 → 产出 Fact"""
        # 认领 Intent
        await self._store.claim_intent(decision.project_id, decision.intent_id)

        # 获取 Intent 详情
        intent = IntentEdge(
            id=decision.intent_id,
            project_id=decision.project_id,
            description=decision.intent_description or "",
        )

        # 记录开始
        log_id = await self._store.log_task_start(
            decision.project_id,
            "explore",
            decision.intent_id,
            "pending",  # session_id 将在 execute 内部获得
        )

        if self._bus:
            try:
                await self._bus.publish(DagTaskStarted, {
                    "project_id": decision.project_id,
                    "task_type": "explore",
                    "session_id": "pending",
                    "log_id": log_id,
                })
            except Exception:
                pass  # Bus publish 不应阻塞调度

        # 启动心跳
        await self._heartbeat_mgr.start_heartbeat(
            decision.project_id, decision.intent_id
        )

        try:
            output = await execute_explore(
                self._session_manager,
                intent,
                snapshot,
                goal_content,
                self._config.get("tasks", {}),
                decision.workspace_path,
            )

            # 写回 Graph Store
            fact_id = output.new_fact.get("id", f"f_{_ts_short()}")
            fact = FactNode(
                id=fact_id,
                project_id=decision.project_id,
                content=output.new_fact.get("content", ""),
                confidence=output.new_fact.get("confidence", 0.5),
                evidence=output.new_fact.get("evidence", ""),
                source_intent_id=decision.intent_id,
                fact_type="discovery",
            )
            await self._store.conclude_intent(
                decision.project_id, decision.intent_id, fact
            )

            # 更新日志
            await self._store.log_task_complete(log_id, "completed", 0, 0, fact.content[:200], 0)

            if output.complete:
                await self._store.update_status(decision.project_id, "completed")
                logger.info("project.completed_via_explore", {"project_id": decision.project_id})

            # 发布图变更事件
            if self._bus:
                await self._bus.publish(GraphStateChanged, {"project_id": decision.project_id})

        except Exception as e:
            logger.error("explore.failed", {"intent_id": decision.intent_id, "error": str(e)})
            await self._store.log_task_complete(log_id, "failed", 0, 0, str(e)[:200], 0)

        finally:
            await self._heartbeat_mgr.stop_heartbeat(
                decision.project_id, decision.intent_id
            )

    def _is_project_at_capacity(self, project_id: str) -> bool:
        return self._running_tasks.get(project_id, 0) >= self._max_project_concurrency


def _ts_short() -> str:
    import time
    return str(int(time.time()))[-6:]
