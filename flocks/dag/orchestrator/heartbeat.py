"""
心跳管理 — 维护运行中 Intent 的存活状态。
"""

import asyncio
from typing import Dict

from flocks.dag.store import GraphStore
from flocks.utils.log import Log

logger = Log.create(service=__name__)


class HeartbeatManager:
    """维护运行中 Intent 的心跳任务"""

    def __init__(
        self,
        store: GraphStore,
        interval: int = 10,
        max_failures: int = 3,
    ):
        self._store = store
        self._interval = interval
        self._max_failures = max_failures
        self._tasks: Dict[str, asyncio.Task] = {}

    async def start_heartbeat(self, project_id: str, intent_id: str):
        """为正在执行的 Intent 启动心跳"""
        key = f"{project_id}:{intent_id}"
        if key in self._tasks:
            return  # 已在运行
        self._tasks[key] = asyncio.create_task(
            self._beat(project_id, intent_id, key),
            name=f"hb-{intent_id}",
        )
        logger.debug("heartbeat.started", {"project_id": project_id, "intent_id": intent_id})

    async def _beat(self, project_id: str, intent_id: str, key: str):
        failures = 0
        while True:
            await asyncio.sleep(self._interval)
            try:
                success = await self._store.heartbeat_intent(project_id, intent_id)
                if not success:
                    failures += 1
                    if failures >= self._max_failures:
                        logger.warning(
                            "heartbeat.lost",
                            {"project_id": project_id, "intent_id": intent_id},
                        )
                        break
                else:
                    failures = 0
            except Exception as e:
                failures += 1
                logger.error("heartbeat.error", {"intent_id": intent_id, "error": str(e)})
                if failures >= self._max_failures:
                    break

        self._tasks.pop(key, None)

    async def stop_heartbeat(self, project_id: str, intent_id: str):
        """停止指定 Intent 的心跳"""
        key = f"{project_id}:{intent_id}"
        task = self._tasks.pop(key, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.debug("heartbeat.stopped", {"intent_id": intent_id})
