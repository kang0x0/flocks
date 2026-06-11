"""
DAG 任务日志 · 会话回放 · SSE 实时推送 API。
"""

import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from flocks.dag.store import GraphStore
from flocks.utils.log import Log

logger = Log.create(service=__name__)


def create_tasks_router(
    store: GraphStore,
    orchestrator,  # DagOrchestrator
    session_manager=None,
    bus=None,
) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["DAG Tasks"])

    # ---- 任务日志 ----

    @router.get("/{project_id}/tasks")
    async def list_project_tasks(project_id: str, limit: int = 50):
        """列出项目的所有任务日志"""
        logs = await store.list_task_logs(project_id, limit)
        return {"tasks": logs, "count": len(logs)}

    @router.get("/{project_id}/tasks/{log_id}")
    async def get_task_log(project_id: str, log_id: int):
        """获取单个任务日志"""
        log = await store.get_task_log(log_id)
        if not log:
            raise HTTPException(404, "任务日志不存在")
        return log

    # ---- 会话回放 ----

    @router.get("/{project_id}/tasks/{log_id}/session")
    async def get_task_session(project_id: str, log_id: int):
        """获取指定任务的完整会话记录（通过 Flocks Session API）"""
        if session_manager is None:
            raise HTTPException(503, "Session 服务不可用")

        log = await store.get_task_log(log_id)
        if not log or not log.get("session_id"):
            raise HTTPException(404, "会话记录不存在")

        try:
            session = await session_manager.get_session(log["session_id"])
        except Exception as e:
            raise HTTPException(503, f"无法获取会话: {e}")

        # 防御性访问
        messages = getattr(session, 'messages', []) or []
        return {
            "session_id": log["session_id"],
            "provider": getattr(session, 'provider', 'unknown'),
            "model": getattr(session, 'model', 'unknown'),
            "rounds": getattr(session, 'rounds', len(messages)),
            "tool_calls": getattr(session, 'tool_calls', []),
            "messages": [
                {
                    "role": getattr(msg, 'role', ''),
                    "content": str(getattr(msg, 'content', ''))[:500],
                    "tool_calls": getattr(msg, 'tool_calls', None),
                    "timestamp": str(getattr(msg, 'timestamp', '')),
                }
                for msg in messages
            ],
            "duration_seconds": getattr(session, 'duration', 0),
        }

    # ---- SSE 实时推送 ----

    @router.get("/{project_id}/tasks/{log_id}/stream")
    async def stream_task_live(project_id: str, log_id: int):
        """SSE 实时推送任务进度"""
        if bus is None:
            raise HTTPException(503, "事件总线不可用")

        async def generator():
            # 简单轮询模式：定期检查任务状态
            last_status = None
            for _ in range(120):  # 最多 10 分钟
                try:
                    log = await store.get_task_log(log_id)
                    if log and log.get("status") != last_status:
                        last_status = log["status"]
                        yield f"data: {json.dumps(log, default=str)}\n\n"
                        if log["status"] in ("completed", "failed", "timeout"):
                            break
                except Exception:
                    pass
                await asyncio.sleep(2)
            yield f"data: {json.dumps({'type': 'stream_ended'})}\n\n"

        return StreamingResponse(generator(), media_type="text/event-stream")

    return router
