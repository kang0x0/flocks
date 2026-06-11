"""
DAG 模块数据模型 — Pydantic 定义，与 SQL 表结构对应。
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


# ============================================================
# 枚举
# ============================================================

class ProjectStatus(str, Enum):
    ACTIVE = "active"
    STOPPED = "stopped"
    COMPLETED = "completed"


class IntentStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    REASON = "reason"
    EXPLORE = "explore"


class HintType(str, Enum):
    GUIDANCE = "guidance"
    CORRECTION = "correction"
    QUESTION = "question"


class FactType(str, Enum):
    ORIGIN = "origin"
    GOAL = "goal"
    DISCOVERY = "discovery"
    CONCLUSION = "conclusion"


# ============================================================
# 核心实体
# ============================================================

class FactNode(BaseModel):
    """确认事实（白盒）"""
    id: str                                     # "origin" / "goal" / "f001" ...
    project_id: str
    content: str                                # 事实描述
    fact_type: str = FactType.DISCOVERY.value   # origin | goal | discovery | conclusion
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: Optional[str] = None              # 支撑证据
    source_intent_id: Optional[str] = None      # 来源意图 ID


class IntentEdge(BaseModel):
    """探索意图（黑盒·DAG 边）"""
    id: str                                     # "i001" / "i_seed" ...
    project_id: str
    description: str                            # 意图描述
    status: IntentStatus = IntentStatus.OPEN
    source_fact_ids: List[str] = Field(default_factory=list)
    priority: int = 0                           # 0 = 最高优先级
    claimed_by: Optional[str] = None
    result_fact_id: Optional[str] = None
    created_by_task: str = "reason"             # reason | seed


class Hint(BaseModel):
    """人类注入提示（灰盒）"""
    id: str
    project_id: str
    content: str
    hint_type: str = HintType.GUIDANCE.value
    created_by: Optional[str] = None
    is_read: bool = False


class DagProject(BaseModel):
    """探索项目"""
    id: str
    title: str
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    origin_fact_id: str = "origin"
    goal_fact_id: str = "goal"
    max_intents_per_reason: int = 3
    seed_intent_id: Optional[str] = None


# ============================================================
# 图快照 & 调度
# ============================================================

class GraphSnapshot(BaseModel):
    """图快照，用于构造 Agent Prompt 和 WebUI 渲染"""
    project_id: str
    project_title: str
    status: ProjectStatus
    origin_fact: Optional[FactNode] = None
    goal_fact: Optional[FactNode] = None
    facts: List[FactNode] = Field(default_factory=list)
    open_intents: List[IntentEdge] = Field(default_factory=list)
    all_intents: List[IntentEdge] = Field(default_factory=list)
    unread_hints: List[str] = Field(default_factory=list)
    statistics: dict = Field(default_factory=dict)


class ScheduleDecision(BaseModel):
    """调度决策"""
    project_id: str
    task_type: TaskType
    intent_id: Optional[str] = None
    intent_description: Optional[str] = None
    workspace_path: str = ""
    timeout: int = 600
    conclude_timeout: int = 120


class ScheduleLog(BaseModel):
    """调度日志"""
    id: int = 0
    project_id: str
    task_type: str                          # reason | explore
    intent_id: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "started"                 # started | completed | failed | timeout
    rounds: int = 0
    tool_calls_count: int = 0
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0


# ============================================================
# 预分析
# ============================================================

class PreAnalysisResult(BaseModel):
    """AI 预分析结果"""
    analyzable: bool = True
    origin: Optional[str] = None
    goal: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_info: List[str] = Field(default_factory=list)
    clarification_questions: List[str] = Field(default_factory=list)


# ============================================================
# 校验
# ============================================================

class ReasonOutput(BaseModel):
    """Reason Agent 输出契约"""
    complete: bool
    reasoning: str
    new_intents: list = Field(default_factory=list)
    complete_rationale: Optional[str] = None


class ExploreOutput(BaseModel):
    """Explore Agent 输出契约"""
    new_fact: dict
    complete: bool = False
