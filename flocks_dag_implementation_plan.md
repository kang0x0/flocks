# Flocks DAG + 黑白模型动态 Agent 调度实现方案

> 版本：2.4.0  
> 最后更新：2026-06-11  
> 目标：在 Flocks 中实现基于 DAG（有向无环图）和黑白模型（Fact-Intent Graph）的动态 Agent 调度引擎

---

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 核心理念](#2-核心理念)
- [3. 关键设计决策（讨论结论）](#3-关键设计决策讨论结论)
- [4. 架构设计](#4-架构设计)
- [5. 数据模型](#5-数据模型)
- [6. 核心模块详解](#6-核心模块详解)
- [7. 调度逻辑](#7-调度逻辑)
- [8. Agent 定义与执行](#8-agent-定义与执行)
- [9. 项目创建与预分析](#9-项目创建与预分析)
- [10. 审计与会话查看](#10-审计与会话查看)
- [11. 与 Flocks 现有模块的集成](#11-与-flocks-现有模块的集成)
- [12. 相对 Cairn 的优化](#12-相对-cairn-的优化)
- [13. 实现路线图](#13-实现路线图)

---

## 1. 背景与目标

### 1.1 当前 Flocks 的 Agent 调用模型

Flocks 当前采用**静态委托模式**：主控 Agent（Rex）根据任务域和触发词，通过 `delegate_task()` 将任务一次性委托给子 Agent。这是一种**请求-响应**式的调用，存在以下局限：

- Agent 之间没有**共享状态图**，无法基于全局探索进度做决策
- 每次委托独立，缺乏**持续调度循环**
- 无法表示"已知事实 vs 待探索方向"的 DAG 结构
- 调度基于静态触发词匹配，而非动态图状态推理

### 1.2 目标

构建 **Dynamic DAG Orchestrator（动态 DAG 编排器）**，实现：

1. **Fact-Intent 共享黑板**：所有 Agent 通过统一状态图间接协作（Stigmergy）
2. **两类调度任务**：Reason（态势推理）+ Explore（意图探索），Bootstrap 合并入 Explore
3. **动态 Agent 调度**：根据任务类型和负载自动选择执行单元
4. **ReAct 循环执行**：每个任务复用 Flocks Session 的 ReAct 多轮思考-工具调用能力
5. **AI 辅助项目创建**：自动分析用户输入，提取起点和目标
6. **实时审计可视**：DAG 任务会话记录实时可查

---

## 2. 核心理念

### 2.1 三元组抽象

| 概念 | 含义 | 在 Flocks 中的角色 |
|------|------|-------------------|
| **Fact（事实·白盒）** | 已确认的客观发现 | Agent 执行探索后写入，作为推理的坚实基础节点 |
| **Intent（意图·黑盒）** | 声明的探索方向 | Reason Agent 提出，表示"从某些事实出发希望探索什么" |
| **Hint（提示·灰盒）** | 人类注入的判断 | 操作员在任意时刻写入，下次 Reason 推理时自动吸收 |

图从 `origin` 起点生长向 `goal` 目标。**白盒**（Fact）代表已知领域，**黑盒**（Intent）代表未知领域，DAG 的扩展即"从已知向未知推进"。

### 2.2 协作模型：Stigmergy（间接协作）

Agent 之间**不直接通信**，所有 Agent 仅通过共享状态图协调：

```
┌──────────────────────────────────────────┐
│           Shared State Graph              │
│  Facts (白) + Intents (黑) + Hints (灰)  │
├──────────────────────────────────────────┤
│  Observe → Orient → Decide → Act (OODA)  │
└──────────────────────────────────────────┘
        ↑                ↑
   Reason Task      Explore Task
   (读图+提出Intent)  (执行Intent+产出Fact)
```

---

## 3. 关键设计决策（讨论结论）

以下为与 Cairn 对比及方案讨论后的**最终设计决策**：

### 3.1 三任务 → 两任务

| 决策 | 说明 |
|------|------|
| ❌ **不保留 Bootstrap** | Bootstrap 本质是从 `origin` 向 `goal` 的一次 Explore，语义可统一 |
| ✅ **项目创建时自动生成 seed_intent** | `origin → [Intent: seed_exploration] → goal`，用 Explore 执行 |
| ✅ **两任务：Reason + Explore** | 调度循环中只需两种决策分支 |

### 3.2 Agent 定义方式

| 决策 | 说明 |
|------|------|
| ❌ **不定义 YAML Agent** | 不需要 `dag_reason`、`dag_explore` 等 Agent YAML 配置 |
| ✅ **Prompt 文件即 Agent** | `dag/prompts/{task}.md` 定义 Agent 行为 |
| ✅ **模型/工具按任务类型在 dag.yaml 配置** | 不同任务绑定不同 Provider、Model、Tools |

### 3.3 Agent 执行方式

| 决策 | 说明 |
|------|------|
| ❌ **不搞单次 LLM 调用** | 发 Prompt 拿结果无法利用工具生态 |
| ❌ **不走 Agent 委托（delegate_task）** | 增加了不必要的耦合层 |
| ✅ **直接调用 Flocks Session API → ReAct 循环** | 复用成熟的 Session Loop：多轮思考→工具调用→观察→再思考 |

### 3.4 项目创建

| 决策 | 说明 |
|------|------|
| ✅ **AI 预分析** | 用户输入自然语言，LLM 自动提取 origin 和 goal |
| ✅ **用户确认/编辑** | 分析结果可编辑，置信度不足时引导用户手动填写 |

### 3.5 审计与会话查看

| 决策 | 说明 |
|------|------|
| ✅ **dag_schedule_log 关联 session_id** | 每个 DAG Task 关联到 Flocks Session（逻辑引用，非数据库外键） |
| ✅ **SSE 实时推送** | 通过 Bus 事件 + EventSource 实时展示 ReAct 每轮进度 |
| ✅ **HTTP API 暴露会话历史** | 可按项目/任务查询完整消息记录 |

### 3.6 Flocks 代码侵入策略（分层原则）

| 层级 | 说明 | 是否允许修改 Flocks 代码 | 示例 |
|------|------|:--:|------|
| **核心逻辑层** | Storage、Session、Agent、Provider、Task 等 | ❌ 禁止 | 不改 `flocks/storage/`、`flocks/session/` 等 |
| **Server 接入层** | FastAPI 路由注册 | ✅ 允许（薄层） | 在 `flocks/server/routes/` 中注册 `dag_router` |
| **WebUI 展示层** | 前端路由、侧边栏菜单项、DAG 页面组件 | ✅ 允许（薄层） | 新增 `webui/src/routes/dag/` 页面 |
| **配置层** | Config 模型扩展 | ✅ 允许（薄层） | `config/settings.py` 新增 `DagConfig` |

**原则**：只做"薄层接入"——即添加调用入口（路由、页面、菜单），不修改任何已有业务逻辑。这些修改是**纯增量**的，拉取上游代码时产生的冲突仅限于新增行，极易解决。

**数据库保持不变**：DAG 数据仍使用独立 `dag.db`（`~/.flocks/dag/dag.db`），不修改 Flocks 原生数据库表结构。

---

## 4. 架构设计

### 4.1 总体架构

```
┌──────────────────────────────────────────────────────────┐
│                    Flocks Platform                        │
│                                                          │
│  ┌──────────────────┐  ┌──────────────┐  ┌────────────┐│
│  │    Graph Store   │  │ Orchestrator │  │Pre-Analyzer││
│  │    (独立 dag.db)  │  │ (自管理循环) │  │            ││
│  └────────┬─────────┘  └──────┬───────┘  └─────┬──────┘│
│           │                   │                 │        │
│           └───────────────────┼─────────────────┘        │
│                               │ import (库引用)           │
│           ┌───────────────────┼─────────────────┐        │
│           ▼                   ▼                  ▼        │
│  ┌──────────────── Flocks 基础设施 ────────────────┐    │
│  │  Session │ Provider │ Bus │ Sandbox │ Memory   │    │
│  │  (不改核心逻辑，仅 import 调用)                  │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─── 薄层接入（仅添加调用入口，不改已有逻辑）────┐     │
│  │                                                 │     │
│  │  FastAPI: 注册 dag_router (增量路由)            │     │
│  │  WebUI:   新增 DAG 页面 + 菜单入口 (增量组件)   │     │
│  │  Config:  扩展 DagConfig (增量配置)             │     │
│  └─────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

### 4.2 新模块目录结构

```
flocks/
├── dag/                              # 新增：DAG 编排模块
│   ├── __init__.py                   # 模块入口（启动 Orchestrator + 注册路由）
│   ├── db.py                         # 独立 SQLite 连接管理（dag.db）
│   ├── store.py                      # Fact/Intent/Hint CRUD
│   ├── models.py                     # Pydantic 数据模型
│   ├── graph.py                      # DAG 图操作 + Mermaid 导出
│   ├── pre_analysis.py               # AI 预分析
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── loop.py                   # 主调度循环
│   │   ├── scheduler.py              # 调度决策
│   │   ├── tasks/
│   │   │   ├── reason.py             # Reason 任务
│   │   │   └── explore.py            # Explore 任务
│   │   ├── heartbeat.py              # 心跳/租约
│   │   └── contracts.py              # 输出校验
│   ├── prompts/                      # Prompt 模板
│   │   ├── pre_analysis.md
│   │   ├── reason.md
│   │   ├── explore.md
│   │   └── explore_conclude.md
│   └── routes/                       # HTTP API 路由
│       ├── projects.py               # 项目 CRUD + 预分析
│       ├── facts.py                  # Fact 管理
│       ├── intents.py                # Intent 管理
│       ├── hints.py                  # Hint 管理
│       └── tasks.py                  # 任务日志 + 会话回放 + SSE

webui/src/routes/                     # 增量：DAG 前端页面
└── dag/
    ├── index.tsx                     # DAG 项目列表页
    ├── project.tsx                   # 项目详情页（含图可视化）
    ├── components/
    │   ├── DagGraph.tsx              # Mermaid 图渲染组件
    │   ├── FactNode.tsx              # Fact 节点详情
    │   ├── IntentEdge.tsx            # Intent 边详情
    │   ├── HintPanel.tsx             # Hint 管理面板
    │   └── TaskLog.tsx               # 任务日志/会话回放
    └── api.ts                        # DAG API 调用封装

config/
└── settings.py                       # 扩展：新增 DagConfig 段（增量配置）


**配置分层说明**：

| 配置文件 | 路径 | 用途 |
|---------|------|------|
| `dag.yaml` | `~/.flocks/config/dag.yaml` | DAG 专有配置（调度间隔、任务超时、模型绑定、Prompt 文件路径等） |
| `config/settings.py` | `flocks/config/settings.py` | Flocks 原生配置扩展，仅在 `Settings` 类中新增 `DagConfig` 引用（薄层增量） |

```
config/settings.py          ~/.flocks/config/dag.yaml
┌──────────────────────┐    ┌────────────────────────────┐
│ class Settings:       │    │ schedule:                  │
│   ...                 │    │   interval: 5              │
│   dag: DagConfig = {} │───▶│   heartbeat_interval: 10   │
│                       │    │ tasks:                     │
│                       │    │   reason:                  │
│                       │    │     provider: openai       │
│                       │    │     model: gpt-4o          │
│                       │    │   explore:                 │
│                       │    │     ...                    │
└──────────────────────┘    └────────────────────────────┘
  （1 行薄层增量）              （独立 DAG 配置文件）
```

**数据文件**（独立于 Flocks 数据库）：

```
~/.flocks/
├── dag/                              # DAG 模块专属数据目录
│   └── dag.db                        # 独立 SQLite 数据库
├── flocks.db                         # Flocks 原生数据库（不修改）
└── ...
```

**DAG 模块启动方式**（`dag/__init__.py`）：

```python
# dag/__init__.py

from dag.db import get_db
from dag.store import GraphStore
from dag.orchestrator.loop import DagOrchestrator
from dag.routes import create_dag_router  # 返回 APIRouter 实例


async def init_dag(flocks_session_manager, flocks_bus, config_path: str):
    """初始化 DAG 模块

    由 Flocks 启动流程调用（在 server/app.py 或 server/__init__.py 中）。
    返回 dag_router 供 Flocks FastAPI app.include_router() 注册。
    """
    config = DagConfig.from_yaml(config_path)
    store = GraphStore(await get_db())
    orchestrator = DagOrchestrator(store, flocks_session_manager, flocks_bus, config)
    dag_router = create_dag_router(store, orchestrator, config)

    # 启动调度循环
    asyncio.create_task(orchestrator.start())

    return dag_router
```

**Flows Server 接入点**（`flocks/server/app.py`，增量行，易合并）：

```python
# ... 原有 import ...
from dag import init_dag  # 新增

# ... 原有 app 初始化 ...
dag_router = await init_dag(session_manager, bus, "~/.flocks/config/dag.yaml")
app.include_router(dag_router, prefix="/dag", tags=["DAG"])
```

> Flocks Server 只需增加 2 行即可接入 DAG 模块：`import` + `app.include_router()`。这是标准 FastAPI 路由注册模式，合并冲突极易解决。

### 4.3 模块依赖关系

```
db.py ──▶ aiosqlite（独立连接，不碰 Flocks Storage）

pre_analysis.py ──▶ Session ──▶ Provider

orchestrator/
  loop.py ──▶ scheduler.py ──▶ tasks/reason.py ──▶ Session ──▶ Provider
            │                 │
            │                 └──▶ tasks/explore.py ──▶ Session ──▶ Provider
            │
            ├──▶ heartbeat.py ──▶ store.py ──▶ db.py
            └──▶ contracts.py

routes/ ──▶ store.py + orchestrator/
  │
  └──▶ 注册到 Flocks FastAPI（app.include_router，增量 1 行）

webui/src/routes/dag/ ──▶ dag/routes/ API（前端独立组件目录）
```

**分层原则**：
- `db.py / store.py / orchestrator/` → 核心逻辑，**零侵入** Flocks
- `routes/` → Server 接入层，通过 FastAPI `include_router` 注册（薄层增量）
- `webui/src/routes/dag/` → WebUI 展示层，新增页面组件（薄层增量）

---

## 5. 数据模型

### 5.1 SQL 表定义（独立数据库 `~/.flocks/dag/dag.db`）

以下所有表均位于 DAG 模块专属的独立 SQLite 数据库中，**不修改 Flocks 原生数据库**。`session_id` 字段为逻辑引用（TEXT），通过 Flocks Session API 查询回放，不做跨库 JOIN。

```sql
-- 探索项目
CREATE TABLE dag_projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'active',              -- active | stopped | completed
    origin_fact_id TEXT NOT NULL,               -- 起点事实 ID
    goal_fact_id TEXT NOT NULL,                 -- 目标事实 ID
    max_intents_per_reason INTEGER DEFAULT 3,   -- 每次 Reason 最多提出多少 Intent
    seed_intent_id TEXT,                        -- 项目创建时自动生成的种子 Intent
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Facts（白盒·确认事实）
CREATE TABLE dag_facts (
    id TEXT NOT NULL,                           -- "origin" / "goal" / "f001" ...
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,                      -- 事实描述
    fact_type TEXT DEFAULT 'discovery',         -- origin | goal | discovery | conclusion
    confidence REAL DEFAULT 1.0,               -- 置信度 0.0-1.0
    evidence TEXT,                              -- 支撑证据
    created_by_task TEXT,                       -- 创建于哪个任务（reason/explore）
    source_intent_id TEXT,                      -- 来源意图
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, project_id),
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);

-- Intents（黑盒·探索意图）
CREATE TABLE dag_intents (
    id TEXT NOT NULL,                           -- "i001" ...
    project_id TEXT NOT NULL,
    description TEXT NOT NULL,                  -- 意图描述
    status TEXT DEFAULT 'open',                 -- open | claimed | completed | failed
    claimed_by TEXT,                            -- 认领者标识
    claimed_at TIMESTAMP,
    last_heartbeat_at TIMESTAMP,
    concluded_at TIMESTAMP,
    result_fact_id TEXT,                        -- 结论 Fact
    priority INTEGER DEFAULT 0,
    created_by_task TEXT,                       -- reason / seed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id, project_id),
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);

-- Intent 来源（多对多：一个 Intent 可从多个 Fact 出发）
CREATE TABLE dag_intent_sources (
    intent_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    PRIMARY KEY (intent_id, project_id, fact_id),
    FOREIGN KEY (intent_id, project_id) REFERENCES dag_intents(id, project_id),
    FOREIGN KEY (fact_id, project_id) REFERENCES dag_facts(id, project_id)
);

-- Hints（人类提示·灰盒）
CREATE TABLE dag_hints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content TEXT NOT NULL,
    hint_type TEXT DEFAULT 'guidance',           -- guidance | correction | question
    created_by TEXT,
    is_read INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);

-- 调度日志（session_id 为逻辑引用，通过 Flocks Session API 查询回放）
CREATE TABLE dag_schedule_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    task_type TEXT NOT NULL,                    -- reason | explore
    intent_id TEXT,                             -- Explore 关联的 Intent
    session_id TEXT,                            -- 逻辑引用 Flocks Session ID（非数据库外键）
    status TEXT DEFAULT 'started',              -- started | completed | failed | timeout | fallback
    rounds INTEGER DEFAULT 0,                   -- ReAct 循环轮数
    tool_calls_count INTEGER DEFAULT 0,         -- 工具调用次数
    result_summary TEXT,
    error_message TEXT,
    duration_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES dag_projects(id)
);
```

### 5.2 Pydantic 核心模型

```python
# dag/models.py

from pydantic import BaseModel
from typing import Optional, List
from enum import Enum

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

class FactNode(BaseModel):
    id: str
    project_id: str
    content: str
    fact_type: str = "discovery"
    confidence: float = 1.0
    evidence: Optional[str] = None
    source_intent_id: Optional[str] = None

class IntentEdge(BaseModel):
    id: str
    project_id: str
    description: str
    status: IntentStatus = IntentStatus.OPEN
    source_fact_ids: List[str] = []
    priority: int = 0

class GraphSnapshot(BaseModel):
    """图快照，用于构造 Agent Prompt"""
    project_id: str
    project_title: str
    status: ProjectStatus
    origin_fact: Optional[FactNode]
    goal_fact: Optional[FactNode]
    facts: List[FactNode]
    open_intents: List[IntentEdge]
    unread_hints: List[str]
    statistics: dict

class PreAnalysisResult(BaseModel):
    """预分析结果"""
    analyzable: bool
    origin: Optional[str] = None
    goal: Optional[str] = None
    confidence: float = 0.0
    missing_info: List[str] = []
    clarification_questions: List[str] = []

class ScheduleDecision(BaseModel):
    """调度决策"""
    project_id: str
    task_type: TaskType
    intent_id: Optional[str] = None
    session_config: dict        # provider, model, tools, temperature
    timeout: int
    conclude_timeout: int
```

---

## 6. 核心模块详解

### 6.1 数据库连接管理（`dag/db.py`）

```python
# dag/db.py

import aiosqlite
from pathlib import Path

DATABASE_DIR = Path.home() / ".flocks" / "dag"
DATABASE_PATH = DATABASE_DIR / "dag.db"

_connection: aiosqlite.Connection | None = None

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
    return _connection

async def _migrate(db: aiosqlite.Connection):
    """自动建表/迁移（幂等）"""
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS dag_projects (...);
        CREATE TABLE IF NOT EXISTS dag_facts (...);
        -- ... 其余表定义
    """)
    await db.commit()

async def close_db():
    """关闭数据库连接"""
    global _connection
    if _connection:
        await _connection.close()
        _connection = None
```

### 6.2 Graph Store（`dag/store.py`）

基于独立 `aiosqlite` 连接的持久化层，提供 Fact / Intent / Hint 的完整 CRUD：

```python
from dag.db import get_db

class GraphStore:
    """不依赖 Flocks Storage，使用独立的 dag.db"""

    # === Projects ===
    async def create_project(self, title: str,
                             origin_content: str, goal_content: str) -> str
    async def get_project(self, project_id: str) -> dict
    async def list_active_projects(self) -> List[dict]
    async def update_status(self, project_id: str, status: ProjectStatus)
    async def complete_project(self, project_id: str)

    # === Facts ===
    async def add_fact(self, fact: FactNode) -> FactNode
    async def get_facts(self, project_id: str) -> List[FactNode]
    async def get_origin_fact(self, project_id: str) -> FactNode
    async def get_goal_fact(self, project_id: str) -> FactNode

    # === Intents ===
    async def create_intent(self, intent: IntentEdge) -> IntentEdge
    async def claim_intent(self, project_id: str, intent_id: str) -> bool
    async def conclude_intent(self, project_id: str, intent_id: str,
                               result_fact: FactNode) -> bool
    async def heartbeat_intent(self, project_id: str, intent_id: str) -> bool
    async def get_open_intents(self, project_id: str) -> List[IntentEdge]
    async def release_stale_intents(self, max_heartbeat_age: int)

    # === Hints ===
    async def add_hint(self, project_id: str, content: str,
                        hint_type: str = "guidance") -> str
    async def mark_hints_read(self, project_id: str)
    async def get_unread_hints(self, project_id: str) -> List[dict]

    # === Graph ===
    async def export_snapshot(self, project_id: str) -> GraphSnapshot
    async def get_statistics(self, project_id: str) -> dict

    # === Log ===
    async def log_task_start(self, project_id: str, task_type: str,
                              intent_id: str, session_id: str) -> int
    async def log_task_complete(self, log_id: int, status: str,
                                 rounds: int, tool_calls: int,
                                 result_summary: str, duration: float)
```

### 6.3 Graph 操作（`dag/graph.py`）

```python
class FactIntentGraph:

    @staticmethod
    def to_mermaid(snapshot: GraphSnapshot) -> str:
        """导出 Mermaid 流程图，用于 WebUI 可视化"""

    @staticmethod
    def to_yaml(snapshot: GraphSnapshot) -> str:
        """导出 YAML 格式，注入 Agent Prompt"""

    @staticmethod
    def find_paths_to_goal(snapshot: GraphSnapshot) -> List[List[str]]:
        """查找从 origin 到 goal 的所有路径"""

    @staticmethod
    def find_frontier_facts(snapshot: GraphSnapshot) -> List[FactNode]:
        """找出尚无 Intent 指出的前沿 Facts（探索前沿）"""

    @staticmethod
    def compute_progress(snapshot: GraphSnapshot) -> float:
        """估算探索进度 0.0-1.0"""
```

### 6.4 Orchestrator 调度循环（`dag/orchestrator/loop.py`）

```python
class DagOrchestrator:
    """DAG 编排器主循环

    使用自管理的 asyncio 循环（不依赖 Flocks TaskManager）
    可配置间隔（默认 5 秒）
    """

    def __init__(self, graph_store: GraphStore,
                 session_manager, bus, config: DagConfig):
        self._store = graph_store
        self._session_manager = session_manager
        self._bus = bus
        self._config = config
        self._scheduler = Scheduler(config)
        self._heartbeat_mgr = HeartbeatManager(graph_store)
        self._running = False

    async def start(self):
        """启动调度循环（自管理 asyncio，零侵入 Flocks）"""
        self._running = True
        while self._running:
            try:
                await self.tick()
            except Exception as e:
                logger.error(f"Orchestrator tick error: {e}")
            await asyncio.sleep(self._config.schedule_interval)

    async def stop(self):
        """停止调度循环"""
        self._running = False

    async def tick(self):
        """单个调度周期"""
        # 1. 获取 active 项目
        active_projects = await self._store.list_active_projects()
        if not active_projects:
            return

        # 2. 释放僵尸 Intent（心跳超时）
        await self._store.release_stale_intents(
            self._config.heartbeat_timeout
        )

        # 3. 逐项目调度决策
        for project in active_projects:
            if self._is_at_capacity(project["id"]):
                continue
            decision = await self._scheduler.decide(
                project["id"], self._store
            )
            if decision:
                asyncio.create_task(self._dispatch(decision))

    async def _dispatch(self, decision: ScheduleDecision):
        """派发任务 → 创建 Session → ReAct 循环 → 校验 → 写回"""
        config = self._config.tasks[decision.task_type.value]

        # 构建 Session 配置
        session = await self._session_manager.create(
            directory=decision.workspace_path,
            provider=config.provider,
            model=config.model,
            system_prompt=decision.rendered_prompt,
            tools=config.tools,
            temperature=config.temperature,
        )

        # 记录日志
        log_id = await self._store.log_task_start(
            decision.project_id,
            decision.task_type.value,
            decision.intent_id,
            session.id,
        )

        # 发布任务开始事件
        await self._bus.publish(DagTaskStarted, {
            "project_id": decision.project_id,
            "task_type": decision.task_type.value,
            "session_id": session.id,
            "log_id": log_id,
        })

        # 启动心跳（Explore 任务）
        if decision.intent_id:
            await self._heartbeat_mgr.start_heartbeat(
                decision.project_id, decision.intent_id
            )

        try:
            # Phase 1: 主执行
            response = await asyncio.wait_for(
                session.send_message(decision.trigger_message),
                timeout=decision.timeout,
            )
            result = validate_output(decision.task_type, response)

            # 校验不通过 → Phase 2: Conclude Fallback
            if not result.is_valid:
                fallback_prompt = self._render_fallback_prompt(decision)
                response = await asyncio.wait_for(
                    session.send_message(fallback_prompt),
                    timeout=decision.conclude_timeout,
                )
                result = validate_output(decision.task_type, response)

            # 写回 Graph Store
            await self._persist_result(decision, result)
            stats = self._compute_session_stats(session)
            await self._store.log_task_complete(
                log_id, "completed",
                stats["rounds"], stats["tool_calls_count"],
                result.summary, session.duration if hasattr(session, 'duration') else 0,
            )

        except asyncio.TimeoutError:
            await self._store.log_task_complete(
                log_id, "timeout", 0, 0, "", decision.timeout
            )
        finally:
            if decision.intent_id:
                await self._heartbeat_mgr.stop_heartbeat(decision.intent_id)
            await session.close()

    def _compute_session_stats(self, session):
        """从 Session 消息历史提取统计（不依赖 Session 内部属性）"""
        messages = getattr(session, 'messages', []) or []
        tool_calls = sum(
            1 for m in messages if getattr(m, 'role', '') == 'assistant'
            and getattr(m, 'tool_calls', None)
        )
        return {
            "rounds": len([m for m in messages if getattr(m, 'role', '') == 'user']),
            "tool_calls_count": tool_calls,
        }
```

### 6.5 调度决策器（`dag/orchestrator/scheduler.py`）

```python
class Scheduler:
    """两阶段决策：Reason 优先？Explore 优先？"""

    async def decide(self, project_id: str,
                     store: GraphStore) -> Optional[ScheduleDecision]:
        """
        决策优先级（每个周期）：
        1. 有 Open Intent → 派发 Explore（优先推进已有探索方向）
        2. 有新 Fact / Hint → 派发 Reason（重新评估态势）
        3. 以上都不满足 → 跳过，等待新事件
        """
        snapshot = await store.export_snapshot(project_id)

        # Priority 1: 有 Open Intent → Explore
        open_intents = await store.get_open_intents(project_id)
        if open_intents:
            intent = self._select_best_intent(open_intents)
            return self._build_decision(
                project_id, TaskType.EXPLORE, intent, snapshot
            )

        # Priority 2: 有新信息 → Reason
        if self._has_new_information(snapshot):
            return self._build_decision(
                project_id, TaskType.REASON, None, snapshot
            )

        return None

    def _select_best_intent(self, intents: List[IntentEdge]) -> IntentEdge:
        """选择最优 Intent：优先级高 + 可能产出大"""
        return sorted(intents,
                      key=lambda i: (-i.priority, len(i.source_fact_ids)))[0]

    def _build_decision(self, project_id, task_type, intent, snapshot):
        """构造完整的调度决策"""
        config = self._config.tasks[task_type.value]
        prompt = self._render_prompt(task_type, intent, snapshot)

        return ScheduleDecision(
            project_id=project_id,
            task_type=task_type,
            intent_id=intent.id if intent else None,
            rendered_prompt=prompt,
            trigger_message=self._trigger_message(task_type),
            session_config={
                "provider": config.provider,
                "model": config.model,
                "tools": config.tools,
                "temperature": config.temperature,
            },
            timeout=config.timeout,
            conclude_timeout=config.conclude_timeout,
        )
```

### 6.6 任务执行器

#### Reason Prompt 模板（`dag/prompts/reason.md`）

```markdown
# Reason Task

你是一个态势推理 Agent。你的任务是分析当前探索状态，决定下一步行动。

## 项目目标

{goal_content}

## 当前探索状态

以下 YAML 描述了完整的 Fact-Intent 图：

```yaml
{graph_yaml}
```

## 未读的人类提示

{hints_section}

## 你的任务

1. 阅读所有 Facts，判断是否已达到 Goal
2. 如果**已达到**：声明完成并说明理由
3. 如果**未达到**：提出最多 {max_intents} 个新的探索 Intent

每个 Intent 必须：
- 明确描述要探索什么
- 声明从哪些 Fact 出发（source_fact_ids）
- 指定优先级（0=最高）
- 说明理由（rationale）

## 你可以使用的工具

- `read`：读取文件内容
- `glob`：搜索文件
- `grep`：搜索内容
- `memory_search`：搜索历史记忆

## 输出格式

任务结束时，必须以如下 JSON 代码块作为回复的最后部分：

```json
{
  "complete": false,
  "reasoning": "你对当前状态的推理分析...",
  "new_intents": [
    {
      "description": "探索方向描述",
      "source_fact_ids": ["f001"],
      "priority": 0,
      "rationale": "提出该意图的理由"
    }
  ]
}
```

如果目标已达成：
```json
{
  "complete": true,
  "reasoning": "达成目标的推理过程...",
  "new_intents": []
}
```
```

#### Explore Prompt 模板（`dag/prompts/explore.md`）

```markdown
# Explore Task

你是一个探索执行 Agent。你的任务是执行指定的探索意图并产出新的事实结论。

## 项目目标

{goal_content}

## 你要执行的意图

**{intent_description}**

## 此意图的出发点（已确认的事实）

{source_facts_section}

## 当前全局图状态（参考上下文）

```yaml
{graph_yaml}
```

## 你的任务

1. 理解意图：从出发点出发，执行该意图描述的探索
2. 使用工具进行探测/分析/验证
3. 产出**一个新的事实结论**

## 你可以使用的工具

- `read` / `write` / `edit`：文件读写编辑
- `bash`：执行终端命令
- `glob` / `grep`：搜索文件和内容
- `webfetch` / `websearch`：网络访问
- `lsp`：代码导航和诊断

## 输出格式

任务结束时，必须以如下 JSON 代码块作为回复的最后部分：

```json
{
  "new_fact": {
    "id": "fXXX",
    "content": "事实的完整描述",
    "confidence": 0.95,
    "evidence": "支撑该结论的证据摘要"
  },
  "complete": false
}
```

如果你认为此次探索已直接达成最终目标，设置 `complete: true`：

```json
{
  "new_fact": {
    "id": "goal",
    "content": "已达成目标，因为...",
    "confidence": 1.0,
    "evidence": "..."
  },
  "complete": true
}
```
```

### 6.7 输出校验（`dag/orchestrator/contracts.py`）

```python
from pydantic import BaseModel, ValidationError
import re
import json

class ReasonOutput(BaseModel):
    complete: bool
    reasoning: str
    new_intents: list[dict] = []

class ExploreOutput(BaseModel):
    new_fact: dict
    complete: bool = False

def extract_json_block(text: str) -> str:
    """从文本中提取 JSON 代码块
    
    支持:
    - ```json ... ```
    - ``` ... ```
    - 纯 JSON
    """
    # 策略 1: 提取 ```json ... ``` 代码块
    match = re.search(r'```json\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if match:
        return match.group(1)

    # 策略 2: 提取最后一个 ```...``` 代码块
    blocks = re.findall(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if blocks:
        return blocks[-1]

    # 策略 3: 尝试找文本末尾的裸 JSON
    match = re.search(r'\{[^}]*"new_fact"|\{[^}]*"complete".*\}', text, re.DOTALL)
    if match:
        return match.group(0)

    raise OutputParseError("无法从响应中提取 JSON")

def validate_reason_output(text: str) -> ReasonOutput:
    json_str = extract_json_block(text)
    return ReasonOutput.model_validate_json(json_str)

def validate_explore_output(text: str) -> ExploreOutput:
    json_str = extract_json_block(text)
    return ExploreOutput.model_validate_json(json_str)
```

### 6.8 心跳与租约（`dag/orchestrator/heartbeat.py`）

```python
class HeartbeatManager:
    """维护运行中 Intent 的心跳"""

    def __init__(self, store: GraphStore,
                 interval: int = 10, max_failures: int = 3):
        self._store = store
        self._interval = interval
        self._max_failures = max_failures
        self._tasks: Dict[str, asyncio.Task] = {}

    async def start_heartbeat(self, project_id: str, intent_id: str):
        key = f"{project_id}:{intent_id}"
        self._tasks[key] = asyncio.create_task(
            self._beat(project_id, intent_id)
        )

    async def _beat(self, project_id: str, intent_id: str):
        failures = 0
        while True:
            await asyncio.sleep(self._interval)
            success = await self._store.heartbeat_intent(
                project_id, intent_id
            )
            if not success:
                failures += 1
                if failures >= self._max_failures:
                    break
            else:
                failures = 0

    async def stop_heartbeat(self, project_id: str, intent_id: str):
        key = f"{project_id}:{intent_id}"
        task = self._tasks.pop(key, None)
        if task:
            task.cancel()
```

---

## 7. 调度逻辑

### 7.1 项目状态机

```
              ┌─────────┐
              │ active  │ ◄──────────── (resume)
              └────┬────┘
                   │
        ┌──────────┼──────────┐
        ▼                     ▼
   ┌─────────┐          ┌─────────┐
   │completed│          │ stopped │ ──▶ (resume) ──▶ active
   │ (终态)  │          │ (暂停)  │
   └─────────┘          └─────────┘
```

### 7.2 调度周期决策流程

```
Orchestrator.tick()  (每 5 秒)
  │
  ├─ 获取 active 项目
  ├─ 释放僵尸 Intent（心跳超时 > 2× interval）
  │
  └─ for each project:
       │
       ├─ 检查项目并发上限 → 已达则跳过
       │
       └─ Scheduler.decide():
            │
            ├─ 有 Open Intent? → 选择优先级最高的 → Explore
            │    │
            │    ├─ 创建 Session（绑定 explore 的 provider/model/tools）
            │    ├─ 注入渲染后的 explore.md Prompt
            │    ├─ 认领 Intent + 启动心跳
            │    ├─ 发送触发消息 → ReAct 循环自动运行
            │    │   ├─ Round 1: LLM → bash("nmap ...")
            │    │   ├─ Round 2: LLM → webfetch(...)
            │    │   ├─ Round 3: LLM → 最终结论
            │    │   └─ 完成后记录统计 → SSE 推送完成事件
            │    ├─ 校验输出（contracts）
            │    │   ├─ 通过 → 写回 Fact，标记 Intent completed
            │    │   └─ 失败 → Conclude Fallback（同一 Session）
            │    └─ 停止心跳，关闭 Session
            │
            ├─ 有新 Fact/Hint? → Reason
            │    │
            │    ├─ 创建 Session（绑定 reason 的 provider/model/tools）
            │    ├─ 注入渲染后的 reason.md Prompt（含完整图快照）
            │    ├─ 发送触发消息 → ReAct 循环
            │    └─ 产出新 Intent(s) OR 声明 Complete
            │
            └─ 以上都不满足 → 跳过
```

### 7.3 项目创建时的 seed_intent

```python
async def create_project(title: str, origin: str, goal: str):
    """创建 DAG 项目，自动生成 seed_intent"""

    # 1. 创建项目
    project_id = await store.create_project(title, origin, goal)

    # 2. 写入 origin 和 goal Fact
    await store.add_fact(FactNode(
        id="origin", project_id=project_id,
        content=origin, fact_type="origin"
    ))
    await store.add_fact(FactNode(
        id="goal", project_id=project_id,
        content=goal, fact_type="goal"
    ))

    # 3. 自动生成种子 Intent
    #    origin → [seed_intent] → goal
    await store.create_intent(IntentEdge(
        id="i_seed",
        project_id=project_id,
        description=f"从起点出发，探索达成目标：{goal[:100]}...",
        source_fact_ids=["origin"],
        priority=0,
        created_by_task="seed",
    ))

    return project_id
```

之后调度循环会自动发现这个 Open Intent 并派发 Explore。

### 7.4 并发控制

| 维度 | 参数（可配置） | 说明 |
|------|--------------|------|
| 全局 Session 并发 | `dag.max_global_concurrency` (10) | 所有项目所有任务的总上限 |
| 单项目并发 | `dag.max_project_concurrency` (4) | 一个项目同时运行的任务数 |
| Explore 并发 | `dag.max_explore_concurrency` (3) | 同一项目同时执行的 Explore 数 |
| 单模型并发 | Provider 层的速率限制 | 防止 API Rate Limit |

---

## 8. Agent 定义与执行

### 8.1 设计原则

> **Prompt 即 Agent，Session 即执行器**

- Agent 行为由 `dag/prompts/{task}.md` 中的 Prompt 模板定义
- Agent 执行由 Flocks 的 Session Loop（ReAct）驱动
- 模型和工具在 `dag.yaml` 中按任务类型配置

### 8.2 配置模型

```yaml
# ~/.flocks/config/dag.yaml

schedule:
  interval: 5                       # 调度间隔（秒）
  heartbeat_interval: 10            # 心跳间隔（秒）
  heartbeat_max_failures: 3         # 心跳最大连续失败次数

concurrency:
  max_global: 10                    # 全局并发上限
  max_project: 4                    # 单项目并发
  max_explore: 3                    # 单项目 Explore 并发

tasks:
  reason:
    provider: openai                # 推理用 OpenAI（强推理能力）
    model: gpt-4o
    temperature: 0.2                # 低温度，稳定输出
    timeout: 300                    # 超时（秒）
    prompt_file: reason.md
    tools:                          # 只读工具集
      - read
      - glob
      - grep
      - memory_search

  explore:
    provider: anthropic             # 探索用 Claude（强工具调用）
    model: claude-sonnet-4-20250514
    temperature: 0.4
    timeout: 600
    conclude_timeout: 120           # 收尾阶段超时
    prompt_file: explore.md
    conclude_prompt_file: explore_conclude.md
    tools:                          # 完整工具集
      - read
      - write
      - edit
      - bash
      - glob
      - grep
      - webfetch
      - websearch

pre_analysis:
  provider: openai
  model: gpt-4o-mini                # 轻量模型，降低成本
  temperature: 0.1
  confidence_threshold: 0.6         # 低于此阈值视为不可分析
  prompt_file: pre_analysis.md
```

### 8.3 执行过程示例

以一次渗透测试的 Explore 为例：

```
Explore Intent: "探测目标 192.168.1.100 的开放端口和服务"

Session Loop (ReAct):
────────────────────────────────────────────────
Round 1:
  [LLM] 需要先做端口扫描
  → bash("nmap -sV -p- 192.168.1.100")
  ← 结果: 22/tcp(OpenSSH 8.9), 80/tcp(nginx 1.24), 
          443/tcp(nginx 1.24), 3306/tcp(MySQL 8.0)
────────────────────────────────────────────────
Round 2:
  [LLM] 发现 Web 服务和数据库，探测 Web 应用
  → webfetch("http://192.168.1.100")
  ← 发现登录页面，响应头显示 Laravel 框架
  → bash("curl -I https://192.168.1.100 -k")
  ← Laravel 10.x, PHP 8.2
────────────────────────────────────────────────
Round 3:
  [LLM] MySQL 对外暴露，检查是否弱口令
  → bash("nmap --script mysql-brute ...")
  ← 未发现弱口令
────────────────────────────────────────────────
Round 4:
  [LLM] 已收集足够信息，生成结论
  → Final Response:
  ```json
  {
    "new_fact": {
      "id": "f003",
      "content": "192.168.1.100 开放端口: 22(SSH), 80(HTTP/nginx), 
                  443(HTTPS/nginx), 3306(MySQL 8.0)。 
                  Web 应用为 Laravel 10.x，未发现弱口令",
      "confidence": 0.95,
      "evidence": "nmap 全端口扫描 + HTTP 指纹识别 + MySQL 弱口令检测"
    }
  }
  ```
  → 任务完成后 Orchestrator 记录日志 → Bus 发布完成事件 → SSE 推送到 WebUI
────────────────────────────────────────────────
```

---

## 9. 项目创建与预分析

### 9.1 流程

```
用户输入自然语言
      │
      ▼
┌─────────────────────┐
│  PreAnalysis Agent   │  (单次 LLM 调用, gpt-4o-mini)
│                      │
│  分析自然语言输入     │
│  → 提取 origin / goal │
│  → 评估置信度         │
│  → 缺失信息/追问      │
└──────┬──────────────┘
       │
       ▼
  ┌───────────┐
  │ analyzable?│
  └──┬────┬───┘
     │YES │NO
     ▼    ▼
┌──────┐ ┌──────────────────┐
│用户确认│ │ 告知缺失信息      │
│+编辑  │ │ + 引导用户手动填写 │
└──┬───┘ └──────────────────┘
   │
   ▼
创建项目 + origin/goal Facts + seed_intent
   │
   ▼
Orchestrator 自动开始调度
```

### 9.2 预分析 Prompt

```markdown
# dag/prompts/pre_analysis.md

你是一个任务分析助手。用户会输入自然语言描述的安全任务需求。
请从中提取起点（origin）和目标（goal）。

## 提取要求

1. **起点（origin）**：用户当前已知的初始状态。包括：
   - 目标系统/对象（IP、域名、文件名等）
   - 已有信息（已知配置、已知漏洞等）
   - 环境约束（网络拓扑、权限等）

2. **目标（goal）**：用户期望达成的最终状态。包括：
   - 期望的结论/结果
   - 判定标准（什么算"完成"）
   - 交付物要求（报告、证据等）

## 输出格式

```json
{
  "analyzable": true/false,
  "origin": "起点描述...(analyzable=false时可为null)",
  "goal": "目标描述...(analyzable=false时可为null)",
  "confidence": 0.0-1.0,
  "missing_info": ["缺失信息1", "缺失信息2"],
  "clarification_questions": ["追问1", "追问2"]
}
```
```

### 9.3 实现

```python
# dag/pre_analysis.py

class ProjectAnalyzer:
    CONFIDENCE_THRESHOLD = 0.6

    def __init__(self, session_manager, config):
        self._session_manager = session_manager
        self._config = config

    async def analyze(self, user_input: str) -> PreAnalysisResult:
        # 创建轻量 Session，无工具，单次调用
        ac = self._config.pre_analysis
        session = await self._session_manager.create(
            provider=ac.provider,
            model=ac.model,
            tools=[],
            temperature=ac.temperature,
        )

        prompt = load_prompt("pre_analysis.md")
        response = await session.send_message(
            f"{prompt}\n\n## 用户输入\n\n{user_input}"
        )

        js = extract_json_block(response)
        result = PreAnalysisResult.model_validate_json(js)
        await session.close()
        return result

    def is_confident(self, result: PreAnalysisResult) -> bool:
        return result.analyzable and \
               result.confidence >= self.CONFIDENCE_THRESHOLD
```

### 9.4 HTTP API

```
POST /dag/projects/analyze
  Body: { "user_input": "帮我评估 192.168.1.100 的安全性" }
  Response: {
    "analyzable": true,
    "origin": "目标服务器: 192.168.1.100...",
    "goal": "完成安全评估，识别可利用漏洞...",
    "confidence": 0.92,
    "missing_info": [],
    "clarification_questions": []
  }

POST /dag/projects
  Body: {
    "title": "服务器安全评估",
    "origin": "...",
    "goal": "..."
  }
  Response: { "project_id": "proj_abc123" }
```

---

## 10. 审计与会话查看

### 10.1 数据链路

```
dag_schedule_log.session_id ──▶ flocks_sessions.id
                                      │
                          ┌───────────┼───────────┐
                          ▼           ▼           ▼
                       messages    tool_calls   session_meta
                       (完整消息)   (工具调用)    (模型/时长)
```

### 10.2 实时推送（SSE）

```python
# dag/routes/tasks.py

@router.get("/dag/projects/{project_id}/tasks/{log_id}/stream")
async def stream_task_live(project_id: str, log_id: str):
    """SSE 实时推送任务进度"""
    async def generator():
        queue = await event_bus.subscribe_queue(
            f"dag.task.{project_id}.{log_id}"
        )
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
    return StreamingResponse(generator(), media_type="text/event-stream")
```

前端消费示例：

```javascript
const eventSource = new EventSource(
  `/dag/projects/${projectId}/tasks/${logId}/stream`
);
eventSource.onmessage = (e) => {
  const data = JSON.parse(e.data);
  // 实时更新 UI:
  //   data.round = 3
  //   data.action = "tool_call"
  //   data.detail = { tool: "bash", args: "nmap -sV ..." }
};
```

**Bus 事件定义**（`dag/events.py`）：

```python
from flocks.bus.bus_event import BusEvent

# 任务生命周期事件
DagTaskStarted = BusEvent.define("dag.task.started", {
    "project_id": str, "task_type": str,
    "session_id": str, "log_id": int,
})
DagTaskCompleted = BusEvent.define("dag.task.completed", {
    "project_id": str, "log_id": int,
    "status": str, "rounds": int, "tool_calls_count": int,
})

# 图状态变更事件（Fact/Intent CRUD 后发布，WebUI 实时刷图）
GraphStateChanged = BusEvent.define("dag.graph.state_changed", {
    "project_id": str,
})

# 项目完成事件（可用于通知推送）
ProjectCompleted = BusEvent.define("dag.project.completed", {
    "project_id": str,
    "total_facts": int, "total_intents": int,
    "duration_seconds": float,
})
```

> **当前阶段**：SSE 推送任务开始/完成事件（`DagTaskStarted` / `DagTaskCompleted`）。
> **后续增强**（Phase +）：利用 Flocks Session 内部钩子实现每轮推流（`DagTaskProgress`），在前端实时显示 LLM 思考→工具调用的逐轮动画。

### 10.3 会话回放

```python
@router.get("/dag/projects/{project_id}/tasks/{log_id}/session")
async def get_task_session(project_id: str, log_id: str):
    """获取指定任务的完整会话记录（通过 Flocks Session API，防御性访问）"""
    log = await store.get_task_log(log_id)
    session = await session_manager.get_session(log.session_id)
    messages = getattr(session, 'messages', []) or []
    return {
        "session_id": session.id,
        "provider": getattr(session, 'provider', 'unknown'),
        "model": getattr(session, 'model', 'unknown'),
        "rounds": getattr(session, 'rounds', len(messages)),
        "tool_calls": getattr(session, 'tool_calls', []),
        "messages": [
            {
                "role": getattr(msg, 'role', ''),
                "content": getattr(msg, 'content', '')[:500],
                "tool_calls": getattr(msg, 'tool_calls', None),
                "timestamp": str(getattr(msg, 'timestamp', '')),
            }
            for msg in messages
        ],
        "duration_seconds": getattr(session, 'duration', 0),
    }

@router.get("/dag/projects/{project_id}/tasks")
async def list_project_tasks(project_id: str, limit: int = 50):
    """列出项目的所有任务日志"""
    logs = await store.list_task_logs(project_id, limit)
    return [
        {
            "log_id": log.id,
            "task_type": log.task_type,
            "intent_id": log.intent_id,
            "session_id": log.session_id,
            "status": log.status,
            "rounds": log.rounds,
            "tool_calls_count": log.tool_calls_count,
            "result_summary": log.result_summary,
            "duration_seconds": log.duration_seconds,
            "created_at": log.created_at,
        }
        for log in logs
    ]
```

### 10.4 审计查询

```sql
-- 按项目汇总
SELECT p.title, COUNT(sl.id) AS total_tasks,
       SUM(sl.tool_calls_count) AS total_tool_calls,
       SUM(sl.duration_seconds) AS total_seconds,
       GROUP_CONCAT(DISTINCT sl.session_id) AS session_ids
FROM dag_projects p
JOIN dag_schedule_log sl ON sl.project_id = p.id
GROUP BY p.id;

-- 按任务类型统计
SELECT task_type,
       COUNT(*) AS task_count,
       AVG(rounds) AS avg_rounds,
       AVG(duration_seconds) AS avg_duration
FROM dag_schedule_log
WHERE project_id = ?
GROUP BY task_type;

-- 查找失败任务
SELECT id, task_type, intent_id, status, error_message, created_at
FROM dag_schedule_log
WHERE project_id = ? AND status IN ('failed', 'timeout')
ORDER BY created_at DESC;

-- 按 session_id 列出所有关联任务（用于关联 Flocks Session 审计）
SELECT sl.id, sl.task_type, sl.status, sl.session_id, sl.created_at
FROM dag_schedule_log sl
WHERE sl.session_id IS NOT NULL
ORDER BY sl.created_at DESC;
```

> **注意**：`session_id` 是逻辑引用，无法直接 SQL JOIN Flocks 数据库的 sessions 表。需要通过 Flocks Session API 按 `session_id` 查询会话详情。如需综合审计，可在应用层关联两个数据源。

### 10.5 DAG Web 界面与图可视化

#### 核心原则：融入 Flocks WebUI，薄层接入

DAG 的 Web 界面**直接集成到 Flocks 现有 WebUI**（React/Vite）中，类似于现有的"工作流"功能，通过侧边栏菜单即可进入。后端 API 路由注册到 Flocks 的 FastAPI Server。

```
Flocks WebUI (localhost:8080)
│
├── 侧边栏
│   ├── 会话
│   ├── 工作流        ← 现有
│   ├── DAG 探索       ← 新增（菜单项）
│   ├── 工具
│   └── ...
│
└── 点击 "DAG 探索" → /dag 路由页面
    ├── 项目列表页 (/dag)
    │   ├── 新建项目（预分析流程）
    │   └── 已有项目卡片列表
    │
    └── 项目详情页 (/dag/projects/:id)
        ├── 图可视化区域（Mermaid.js）
        ├── Fact/Intent 列表
        ├── Hint 管理面板
        └── 任务日志 + 会话回放
```

**Flocks 代码改动范围**（纯增量，不改已有逻辑）：

| 文件 | 改动 | 冲突风险 |
|------|------|:--:|
| `flocks/server/app.py` | 新增 `app.include_router(dag_router, prefix="/dag")` | 极低 |
| `webui/src/App.tsx` 或路由配置 | 新增 `/dag` 路由注册 | 低 |
| `webui/src/components/Sidebar.tsx` | 新增菜单项 `<NavLink to="/dag">DAG 探索</NavLink>` | 低 |
| `config/settings.py` | 新增 `DagConfig` 段 | 低 |

#### 图可视化渲染流程

```
数据层                       API 层                      前端渲染
───────                     ────────                    ─────────

GraphSnapshot             GET /dag/projects/           DagGraph.tsx
  │                       {id}/graph/mermaid           (React 组件)
  ▼                            │                           │
FactIntentGraph           "graph LR\n                   Mermaid.js
  .to_mermaid()             origin[...]                 (npm 包或 CDN)
  (生成 Mermaid DSL)         f001[...]                      │
                            ..."                           ▼
                            (JSON 响应)                 渲染为 SVG
                                                          │
变更触发:                                                  ▼
  Fact/Intent CRUD                                   显示在页面
       │
       ▼
  Bus.publish(GraphStateChanged)
       │
       ▼
  SSE /dag/projects/{id}/events → 前端 EventSource → 重新拉取 Mermaid → 更新渲染
```

#### Mermaid 图渲染示例

API 返回的原始 Mermaid 文本（由 `to_mermaid()` 生成）：

```
graph LR
    origin(["起点<br/>目标: 192.168.1.100"])
    f001(["f001<br/>开放端口 22,80,443"])
    f002(["f002<br/>Web 应用 Laravel 10.x"])
    goal(["目标<br/>完成安全评估"])

    origin -->|"i_seed<br/>初始探索"| f001
    f001 -->|"i001<br/>探测Web应用"| f002
    f002 -->|"i002<br/>漏洞检测"| goal

    style origin fill:#e8f5e9,stroke:#2e7d32
    style goal fill:#fff3e0,stroke:#ef6c00
    style f001 fill:#e3f2fd,stroke:#1565c0
    style f002 fill:#e3f2fd,stroke:#1565c0
```

`DagGraph.tsx` 组件使用 Mermaid.js 渲染为交互式流程图：
- **绿色节点** — 起点（origin）、目标（goal）
- **蓝色节点** — 已确认事实（Facts）
- **橙色节点** — 待执行意图（Open Intents）
- **灰色节点** — 已完成意图
- 箭头标签显示 Intent 描述

#### 实时更新机制

```
GraphStore CRUD → Bus.publish(GraphStateChanged) → SSE 推送 → 前端 EventSource
                                                                       │
                                                      重新拉取 GET /graph/mermaid
                                                                       │
                                                            Mermaid.js re-render
```

#### 前端交互功能（Phase 4 实现时细化）

| 功能 | 说明 |
|------|------|
| 新建项目 | 输入自然语言 → 调用 `/dag/projects/analyze` → 用户确认 → 创建 |
| 图浏览 | 缩放/拖拽 Mermaid 图，点击节点查看详情 |
| 实时追踪 | SSE 接收 GraphStateChanged 事件，自动刷图 |
| 手动干预 | 手动添加 Fact / Intent / Hint |
| 会话回放 | 点击任务日志 → 查看完整 ReAct 历史 |

> **Mermaid.js 依赖**：Flocks WebUI 已有 `package.json` 构建体系，可直接 `npm install mermaid` 引入，无需 CDN。

---

## 11. 与 Flocks 现有模块的集成

| Flocks 模块 | 集成方式 | 侵入性 | 作用 |
|------------|---------|:--:|------|
| **Session** | `session_manager.create()` → `session.send_message()` | 零侵入 | 驱动 ReAct 多轮循环 |
| **Provider** | Session 绑定 provider/model | 零侵入 | 不同任务使用不同 LLM |
| **Storage** | **不修改**，DAG 使用独立 `dag.db`（`aiosqlite`） | **零侵入** | DAG 数据隔离，不受上游代码变更影响 |
| **Task** | **不依赖**，Orchestrator 使用自管理 `asyncio` 循环 | **零侵入** | 调度循环独立运行，不受 Flocks TaskManager 影响 |
| **Bus** | 发布 `DagTaskStarted` / `DagTaskProgress` / `DagTaskCompleted` 等事件 | 零侵入 | 解耦通知 + SSE 推送 |
| **Hooks** | `dag.fact.created` / `dag.intent.created` 等生命周期钩子 | 零侵入 | 自定义扩展点 |
| **Permission** | Session 层 `permission` 配置 | 零侵入 | 工具调用的安全管控 |
| **Memory** | Reason 任务可通过 `memory_search` 工具查询历史 | 零侵入 | 跨项目知识复用 |
| **Sandbox** | Explore 任务可启用 Sandbox 隔离 | 零侵入 | Docker 容器安全执行 |
| **Channel** | 重大发现/项目完成时推送通知 | 零侵入 | 多渠道告警 |
| **MCP / LSP** | Explore 任务工具集中可包含 MCP / LSP 工具 | 零侵入 | 工具生态扩展 |
| **WebUI (React)** | 新增 `/dag` 路由页面 + 侧边栏菜单项 + Mermaid 图渲染组件 | **薄层** | DAG 项目列表/详情/图可视化 |
| **Server (FastAPI)** | `app.include_router(dag_router, prefix="/dag")` 注册路由 | **薄层** | HTTP API 暴露 + SSE 推送 |

> **分层原则**：
> - **核心逻辑层**（Session / Provider / Storage / Agent / Sandbox）→ 零侵入，仅 import 调用
> - **接入层**（Server 路由 / WebUI 页面 / Config）→ 薄层增量，仅做入口添加，不改已有逻辑
> - 拉取上游 Flocks 更新时，合并冲突仅限于接入层的少量新增行

---

## 12. 相对 Cairn 的优化

| 维度 | Cairn | Flocks DAG Orchestrator | 优化点 |
|------|-------|------------------------|--------|
| **部署架构** | Server + Dispatcher 两个独立进程 | 内嵌单进程多模块 | 简化运维，减少 IPC |
| **任务类型** | Bootstrap + Reason + Explore（3 种） | Reason + Explore（2 种），Bootstrap 合并 | 更简洁统一 |
| **Agent 定义** | Prompt 文件随代码分发 | Prompt 文件 + dag.yaml 配置 | 配置更灵活 |
| **Agent 执行** | 外部 CLI 进程（Docker exec） | Flocks Session ReAct 循环 | 复用成熟框架，可观测 |
| **模型支持** | 单一模型（Anthropic） | 多 Provider（OpenAI/Anthropic/DeepSeek 等） | 按任务类型选最优模型 |
| **工具生态** | Agent CLI 裸执行 | Flocks 30+ 内置工具 + MCP 扩展 | 工具丰富 |
| **安全** | 无管控 | Permission + Sandbox + Audit | 细粒度安全 |
| **记忆** | 无 | Memory（向量 + BM25 混合搜索） | 跨项目知识复用 |
| **可视化** | 无 | WebUI + Mermaid 图 + SSE 实时推送 | 透明可观测 |
| **上下文** | 无管理 | Session Compaction（自动压缩） | 长探索不丢失上下文 |
| **项目创建** | 手动定义 origin/goal | AI 预分析 + 用户确认 | 降低使用门槛 |
| **审计** | 简单日志 | 完整 Session 回放 + 审计查询 | 满足合规要求 |
| **通知** | 无 | Channel / Notification 多渠道推送 | 及时告警 |
| **扩展** | 无 | Hooks 生命周期 + Plugin 系统 | 可插拔扩展 |
| **配置** | 单一 YAML | 多层级（default → file → env → cli） | 灵活配置 |

---

## 13. 实现路线图

### Phase 1：核心数据层（预估 1-2 周）

- [ ] 实现 `dag/models.py`：所有 Pydantic 模型
- [ ] 实现 `dag/store.py`：Graph Store CRUD（基于独立 `dag.db`，不修改 Flocks Storage）
- [ ] 实现 `dag/graph.py`：图操作工具（Mermaid/YAML 导出、路径查找、进度计算）
- [ ] 编写单元测试

### Phase 2：预分析 + 项目创建（预估 1 周）

- [ ] 编写 `dag/prompts/pre_analysis.md`
- [ ] 实现 `dag/pre_analysis.py`
- [ ] 实现 `dag/routes/projects.py`（analyze + create API 端点）
- [ ] 实现项目创建时的 seed_intent 自动生成逻辑

### Phase 3：调度引擎（预估 2-3 周）

- [ ] 实现 `dag/orchestrator/loop.py`：主调度循环
- [ ] 实现 `dag/orchestrator/scheduler.py`：两阶段决策
- [ ] 实现 `dag/orchestrator/heartbeat.py`：心跳租约
- [ ] 实现 `dag/orchestrator/contracts.py`：输出校验 + JSON 提取
- [ ] 编写 `dag/prompts/reason.md` 和 `dag/prompts/explore.md`
- [ ] 实现 `dag/orchestrator/tasks/reason.py` 和 `explore.py`
- [ ] 实现双阶段（Execute + Conclude Fallback）
- [ ] 与 Flocks Session API 集成（ReAct 循环驱动，仅 import 引用）
- [ ] 实现自管理 asyncio 调度循环（不依赖 Flocks TaskManager）
- [ ] 实现 Bus 事件发布（仅调用 Bus API，不修改 Flocks Bus 模块）

### Phase 4：WebUI 集成 + 审计（预估 1-2 周）

- [ ] **Flocks Server 接入**：`app.include_router(dag_router, prefix="/dag")`，增量 1 行
- [ ] **侧边栏菜单**：新增"DAG 探索"菜单项，增量 1 行
- [ ] 实现 `webui/src/routes/dag/index.tsx`（项目列表页）
- [ ] 实现 `webui/src/routes/dag/project.tsx`（项目详情 + 图可视化）
- [ ] 实现 `DagGraph.tsx`（Mermaid.js 渲染组件 + SSE 实时刷新）
- [ ] 实现 `HintPanel.tsx` / `TaskLog.tsx`（Hint 管理 + 会话回放）
- [ ] 实现 `dag/routes/tasks.py`（任务日志 + SSE 端点）
- [ ] 审计查询功能

### Phase 5：集成与扩展（预估 1-2 周）

- [ ] 与 Flocks Sandbox 集成
- [ ] 与 Flocks Memory 集成
- [ ] 与 Flocks Hooks 集成（注册生命周期钩子）
- [ ] 与 Flocks Channel / Notification 集成
- [ ] 编写 `dag.yaml` 配置模型

### Phase 6：测试与文档（预估 1 周）

- [ ] 端到端集成测试
- [ ] 性能测试（并发、长任务）
- [ ] 用户文档与开发者文档

---

## 附录 A：核心数据流总览

```
用户输入
  │
  ▼
PreAnalyzer (LLM 单次) → origin + goal
  │
  ▼
用户确认/编辑
  │
  ▼
创建项目 + origin/goal Facts + seed_intent
  │
  ▼
┌─────────────────────────────────────────────────┐
│  Orchestrator 调度循环 (每 5s)                    │
│                                                  │
│  for each active project:                       │
│    │                                             │
│    ├─ 有 Open Intent? ──▶ Explore               │
│    │   ├─ Session.create() + explore.md         │
│    │   ├─ send_message() → ReAct 循环            │
│    │   ├─ LLM ←→ bash/webfetch/read/...        │
│    │   ├─ 最终 JSON 输出                         │
│    │   ├─ contracts.validate()                  │
│    │   └─ 新 Fact 写入 Graph Store               │
│    │                                             │
│    └─ 有新信息? ──▶ Reason                      │
│        ├─ Session.create() + reason.md          │
│        ├─ send_message() → ReAct 循环            │
│        ├─ LLM ←→ read/memory_search/...         │
│        ├─ 最终 JSON 输出                         │
│        └─ 新 Intent(s) 写入 Graph Store          │
│                                                  │
│  [每步通过 Bus → SSE 实时推送到 WebUI]            │
└─────────────────────────────────────────────────┘
  │
  ▼
Reason 判定 complete → 项目标记完成
  │
  ▼
通知用户 + 审计留档
```

## 附录 B：配置文件完整示例

```yaml
# ~/.flocks/config/dag.yaml

schedule:
  interval: 5
  heartbeat_interval: 10
  heartbeat_max_failures: 3

concurrency:
  max_global: 10
  max_project: 4
  max_explore: 3

tasks:
  reason:
    provider: openai
    model: gpt-4o
    temperature: 0.2
    timeout: 300
    max_intents: 3
    prompt_file: reason.md
    tools: [read, glob, grep, memory_search]

  explore:
    provider: anthropic
    model: claude-sonnet-4-20250514
    temperature: 0.4
    timeout: 600
    conclude_timeout: 120
    prompt_file: explore.md
    conclude_prompt_file: explore_conclude.md
    tools:
      - read
      - write
      - edit
      - bash
      - glob
      - grep
      - webfetch
      - websearch
      - lsp

pre_analysis:
  provider: openai
  model: gpt-4o-mini
  temperature: 0.1
  confidence_threshold: 0.6
  prompt_file: pre_analysis.md

sandbox:
  enabled: false
  image: flocks/sandbox:latest
  network_mode: host
```

---

> 本文档经多轮讨论修订定稿，涵盖了所有关键设计决策和实现细节。
