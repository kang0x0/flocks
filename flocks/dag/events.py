"""
DAG 模块 Bus 事件定义。

用于 SSE 推送、Hook 触发、通知联动等。
"""

from pydantic import BaseModel, Field
from typing import Optional
from flocks.bus.bus_event import BusEvent


# ================================================================
# 事件 Props
# ================================================================

class _TaskStartedProps(BaseModel):
    project_id: str
    task_type: str
    session_id: str
    log_id: int


class _TaskCompletedProps(BaseModel):
    project_id: str
    log_id: int
    status: str
    rounds: int = 0
    tool_calls_count: int = 0


class _GraphStateChangedProps(BaseModel):
    project_id: str


class _ProjectCompletedProps(BaseModel):
    project_id: str
    total_facts: int = 0
    total_intents: int = 0
    duration_seconds: float = 0.0


# ================================================================
# 事件定义
# ================================================================

DagTaskStarted = BusEvent.define("dag.task.started", _TaskStartedProps)
DagTaskCompleted = BusEvent.define("dag.task.completed", _TaskCompletedProps)
GraphStateChanged = BusEvent.define("dag.graph.state_changed", _GraphStateChangedProps)
ProjectCompleted = BusEvent.define("dag.project.completed", _ProjectCompletedProps)
