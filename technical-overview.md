# Cairn 技术说明文档

## 1. 项目概述

Cairn 是一个基于**事实-意图图（Fact-Intent Graph）**的通用问题求解引擎。它不预设任何角色或工作流，而是将问题求解建模为**有向状态空间搜索**：给定起点（Origin）和目标（Goal），引擎在未知的状态空间中自主寻找路径。

Cairn 首个落地的验证领域是**AI 渗透测试**，但其设计本身不限于此——漏洞研究、CTF 挑战、数学证明等具有"明确起点、明确目标、路径未知"结构的问题均适用。

---

## 2. 核心理念

### 2.1 三元组抽象

Cairn 的核心是一个共享黑板（Blackboard），其上只存在三种基元：

| 概念 | 含义 | 说明 |
|------|------|------|
| **Fact（事实）** | 已确认的客观发现 | 由 Worker 探测并写入黑板，是整个图推理的坚实节点 |
| **Intent（意图）** | 声明的探索方向 | 表示"从某些事实出发，希望探索什么"，尚未执行 |
| **Hint（提示）** | 人类注入的判断 | 由操作员在任意时刻写入，Agent 下次读取时自动吸收 |

图从 `origin`（起点）生长向 `goal`（目标）。每个新 Fact 是前进的垫脚石，每个 Intent 是迈向未知的一步。

### 2.2 协作模型：Stigmergy（间接协作）

Agent Worker 之间**不直接通信**，不共享上下文，不传递消息。所有 Agent 仅通过共享黑板进行协调：

- **Observe（观察）**：读取完整的 Fact-Intent 图
- **Orient（定向）**：理解当前状态与目标的差距
- **Decide（决策）**：决定下一步探索方向或确认目标达成
- **Act（行动）**：执行探索并写回新的 Fact

这种机制消除了信息孤岛，使多 Agent 协作天然可扩展。

---

## 3. 系统架构

Cairn 由三大组件构成：

```
+------------------------------+
|        Cairn Server          |
|  (FastAPI + SQLite)          |
|  Facts / Intents / Hints     |
|  Protocol API                |
+--------------^---------------+
               | HTTP (REST API)
+--------------+---------------+
|         Dispatcher           |
|  (Python 调度引擎)            |
|  调度 / 容器管理 / 健康检查   |
|  超时控制 / 协议写回          |
+-------+---------------+------+
        |               |
  容器管理             容器管理
        |               |
+-------v------+  +----v--------+
| Project 容器A |  | Project 容器B |
| Claude Code   |  | Codex CLI    |
| (Kali Linux)  |  | (Kali Linux) |
+--------------+  +--------------+
```

### 3.1 Cairn Server

**技术栈**：FastAPI + SQLite（无需外部数据库）

职责：
- 保存 Project / Fact / Intent / Hint 的完整状态
- 提供 RESTful 协议接口
- 维护 Intent 的认领（Claim）、心跳（Heartbeat）、结论（Conclude）状态
- 维护项目级 Reason Lease
- 提供 YAML 格式的图导出（用于构造 Agent Prompt）

关键路由：
| 路由 | 功能 |
|------|------|
| `POST /projects` | 创建项目（含 origin/goal 初始 Fact） |
| `GET /projects/{id}` | 获取项目完整详情 |
| `POST /projects/{id}/intents` | 创建新 Intent |
| `POST /projects/{id}/intents/{iid}/heartbeat` | Intent 心跳保活 |
| `POST /projects/{id}/intents/{iid}/conclude` | 结论 Intent 并生成 Fact |
| `POST /projects/{id}/reason/claim` | 认领项目级 Reason 锁 |
| `POST /projects/{id}/complete` | 声明目标达成 |
| `GET /projects/{id}/export?format=yaml` | 导出图快照 |

### 3.2 Dispatcher

**技术栈**：Python 3.12+，依赖 Docker SDK、Requests、PyYAML

Dispatcher 是 Cairn 的控制面，负责一切执行决策。它是**唯一的协议写入者**——Agent 不直接调用 Server API。

核心功能模块：

#### 调度循环（Scheduler Loop）
- 以可配置的间隔（`runtime.interval`）轮询 Server
- 读取所有项目状态，识别 active 项目
- 为每个项目决策下一步任务类型
- 按优先级和负载均衡选择 Worker
- 跨项目公平调度，避免单项目垄断

#### 任务系统（Task System）
三种任务类型，由同一组 Worker 执行：

| 任务 | 触发条件 | 输出 |
|------|----------|------|
| **Bootstrap** | 项目初始态（仅一次） | Fact + 可能的 Complete |
| **Reason** | 新 Fact / Hint 出现时 | Complete / 新 Intents / No-op |
| **Explore** | 有可认领的 Open Intent | 一个 Fact |

其中 Bootstrap 和 Explore 支持**双阶段模式**：
1. 第一阶段：直接执行，尝试产出结果
2. 第二阶段（Conclude Fallback）：若第一阶段超时或解析失败，使用同一 Session 进入收尾阶段，至少产出 Fact

#### 容器管理（Container Manager）
- 每个 Project 对应一个 Docker 容器（Kali Linux 环境）
- 容器生命周期管理：创建、启动、停止、删除
- 通过 `docker exec` 在容器内执行 Worker 进程
- 支持网络模式配置、cap_add 能力添加
- 项目完成后可选择 `stop`（保留现场）或 `remove`（清理）

#### Worker 驱动（Worker Driver）
抽象的 Worker 接口，每种后端模型对应一个 Driver：

| Driver | 后端 | 特点 |
|--------|------|------|
| `claudecode` | Claude Code CLI | 支持 Session，UUID 会话 ID |
| `codex` | Codex CLI | 支持 Session，UUID 会话 ID |
| `pi` | 通用 API | 支持 Session |
| `mock` | 模拟数据 | 用于测试，可配置输出分布 |

每个 Driver 负责：
- 构建健康检查命令
- 构建执行命令（含 Prompt 注入）
- 构建 Conclude 收尾命令
- 提取 Session ID 用于维持多阶段对话上下文

#### 心跳与租约（Heartbeat & Lease）
- 为每个运行中的 Intent 启动后台心跳线程
- 失败容忍：允许短暂失败，超过 `interval × 2` 的持续失败才判定为失效
- Reason Lease：项目级的排他锁，一个项目同时只能有一个 Reason 任务

#### 健康检查（Healthcheck）
三种模式：
| 模式 | 行为 |
|------|------|
| `startup_and_task` | Dispatcher 启动时 + 每次任务前都检查 |
| `startup_only` | 仅启动时检查 |
| `disabled` | 跳过健康检查 |

Worker 健康检查失败后进入短暂不可选窗口（5 秒），避免反复调度同一不可用 Worker。

### 3.3 Worker / Agent CLI

Worker 是被 Dispatcher 管理的执行单元。当前支持的 Agent CLI：
- **Claude Code**（Anthropic Claude）
- **Codex CLI**（OpenAI 兼容 API）
- **Pi**（自定义 API 封装）

Agent **不感知**调度逻辑、不认领 Intent、不维持心跳。Agent 只做三件事：
1. 接收 Dispatcher 渲染好的 Markdown Prompt
2. 执行分析/探测/操作
3. 输出结构化 JSON

---

## 4. 数据模型

### 4.1 核心实体

```sql
-- 项目
projects (id, title, status, bootstrap_enabled, created_at,
          reason_worker, reason_trigger, reason_started_at, reason_last_heartbeat_at)

-- 事实（图中的节点）
facts (id, project_id, description)  -- id 为 "origin" / "goal" / "f001" ...

-- 意图（图中的边）
intents (id, project_id, to_fact_id, description, creator,
         worker, last_heartbeat_at, created_at, concluded_at)

-- 意图来源（多对多关系）
intent_sources (intent_id, project_id, fact_id)

-- 人类提示
hints (id, project_id, content, creator, created_at)
```

### 4.2 图结构

图从 `origin` 出发，经过一系列 Intent → Fact 的推导，最终指向 `goal`：

```
origin ──Intent──▶ Fact(f001) ──Intent──▶ Fact(f002) ──⋯──▶ goal
                         │                                    ↑
                         └──── Intent ────────────────────────┘
```

Intent 可以指向已有的 Fact（探索性结论），也可以指向 `goal`（达成声明）。

### 4.3 Prompt 体系

Prompt 以 Markdown 文件形式分发，位于 `dispatcher/prompts/<group>/` 目录：

| Prompt 文件 | 用途 |
|-------------|------|
| `bootstrap.md` | 初始直接求解 |
| `bootstrap_conclude.md` | Bootstrap 收尾阶段 |
| `reason.md` | 读图推理，判断是否完成或提出新 Intent |
| `explore.md` | 执行指定 Intent 的探索 |
| `explore_conclude.md` | Explore 收尾阶段 |

通过 `runtime.prompt_group` 配置项选择 Prompt 组，支持在不同场景间切换行为。

---

## 5. 调度逻辑

### 5.1 项目状态机

```
created (active) ──▶ completed ──▶ (可 reopen 回 active)
        │
        └──▶ stopped ──▶ (可恢复为 active)
```

- **active**：正常调度
- **stopped**：立即取消本地任务，清理容器，清空 Intent 认领
- **completed**：目标已达成，不再调度

### 5.2 任务优先级

每个调度周期的决策顺序：

1. 有可认领的 **Open Intent** → 优先派发 Explore
2. 出现新 Fact / Hint，需要更新态势 → 派发 Reason
3. 项目初始态且 Bootstrap 启用 → 派发 Bootstrap
4. 上述条件均不满足 → 跳过，等待新事件

### 5.3 Worker 选择算法

1. 按任务类型筛选（`worker.task_types`）
2. 过滤达到 `max_running` 上限的 Worker
3. 过滤处于不可选窗口的不健康 Worker
4. 按 `priority` 升序排序
5. 相同 priority 下，选择运行任务数最少的
6. 仍然相同则随机选择

### 5.4 并发控制

| 维度 | 参数 | 说明 |
|------|------|------|
| 全局任务数 | `max_workers` | 所有项目所有 Worker 的总并发上限 |
| 并行项目数 | `max_running_projects` | 同时调度多少项目 |
| 单项目并发 | `max_project_workers` | 一个项目最多同时运行多少任务 |
| 单 Worker 并发 | `workers[].max_running` | 一个 Worker（如一个 API Key）最多同时运行多少任务 |
| Reason 排他 | 项目级 lease | 一个项目同时只能有一个 Reason 任务 |

---

## 6. 执行主链路

以一次典型的 Explore 任务为例：

```
1. Dispatcher 轮询 Server，发现项目有可认领的 Open Intent
2. 选择 Worker（基于优先级、负载、健康状态）
3. 通过 POST /heartbeat 认领 Intent
4. 确保项目容器正在运行（Docker）
5. （可选）执行健康检查
6. 加载 prompt 模板，渲染图快照等上下文
7. 启动心跳保活线程
8. 在容器内 docker exec Worker CLI（如 `claude`）
9. Worker 执行探测，输出 JSON
10. Dispatcher 解析 JSON，校验 payload
11. 通过 POST /conclude 将结论写回 Server
12. 停止心跳，释放 Intent
```

---

## 7. 配置模型

Dispatcher 使用 YAML 配置文件，一个典型配置包含：

```yaml
server: "http://cairn-server:8000"       # Server 端点

runtime:
  interval: 3                             # 调度间隔（秒）
  max_workers: 8                          # 全局并发
  max_running_projects: 3                 # 并行项目数
  max_project_workers: 4                  # 单项目并发
  healthcheck_timeout: 20                 # 健康检查超时
  worker_healthcheck: "startup_only"      # 健康检查模式
  prompt_group: "default"                 # Prompt 组

tasks:
  bootstrap:
    timeout: 300                          # 超时（秒）
    conclude_timeout: 90                  # 收尾阶段超时
  reason:
    timeout: 300
    max_intents: 2                        # 一次最多提出多少 Intent
  explore:
    timeout: 300
    conclude_timeout: 90

container:
  image: "ghcr.io/oritera/cairn-worker-container:latest"
  network_mode: "host"
  completed_action: "stop"                # 完成后 stop 或 remove

workers:
  - name: "claudecode_main"
    type: "claudecode"
    task_types: [bootstrap, reason, explore]
    max_running: 2
    priority: 0
    env:
      ANTHROPIC_MODEL: "..."
      ANTHROPIC_BASE_URL: "..."
      ANTHROPIC_AUTH_TOKEN: "..."
```

支持配置多种 Worker 类型和多个 Worker 实例，Dispatcher 根据 `type` 自动选择对应的 Driver。

---

## 8. 技术特性

### 8.1 健壮性设计

- **超时防护**：每个任务阶段有独立的超时控制，超时后自动进入 Conclude Fallback 或释放资源
- **心跳保活**：后台心跳线程持续维持 Intent 认领状态，Server 端设置超时自动释放
- **健康检查**：Worker 执行前验证后端可用性，失败后进入退避窗口
- **优雅取消**：项目停止/删除时，通过 `TaskCancellation` 机制通知正在执行的容器进程
- **容器清理**：项目完成后异步并行清理容器，不阻塞主调度循环

### 8.2 设计决策

1. **Agent 不直接调 API**：Agent 只输出结构化 JSON，所有协议交互由 Dispatcher 完成。这使 Agent 逻辑极度简化，且协议变更不影响 Agent。
2. **Prompt 随代码分发**：Prompt 模板与代码版本绑定，避免运行时拉取和版本漂移问题。
3. **单 Dispatcher 实例**：当前设计不支持多 Dispatcher 同时连接同一 Server，避免调度冲突。
4. **状态变化优先日志**：正常轮询不刷日志，仅记录有意义的状态变更，避免日志爆炸。
5. **双阶段任务（Execute + Conclude）**：Agent 在主要执行阶段输出的内容不满足要求时，可以用同一 Session 进入收尾阶段，至少保证产出有价值的结论。

---

## 9. 项目文件结构

```
cairn/
├── src/cairn/
│   ├── __init__.py              # 版本信息
│   ├── cli.py                   # CLI 入口 (serve / dispatch)
│   ├── dispatcher/
│   │   ├── config.py            # 配置模型（YAML -> Pydantic）
│   │   ├── contracts.py         # 输出校验（validate_reason_payload 等）
│   │   ├── logging.py           # 日志配置
│   │   ├── models.py            # 运行时模型（RunningTask, ReasonCheckpoint）
│   │   ├── output_parser.py     # JSON 提取器（从 LLM 输出中提取 JSON）
│   │   ├── prompting.py         # Prompt 加载与渲染
│   │   ├── protocol/
│   │   │   └── client.py        # Cairn Server HTTP 客户端
│   │   ├── runtime/
│   │   │   ├── cancellation.py  # 任务取消机制
│   │   │   ├── containers.py    # Docker 容器管理
│   │   │   ├── heartbeat.py     # 心跳租约
│   │   │   └── process.py       # 容器内进程管理
│   │   ├── scheduler/
│   │   │   ├── loop.py          # 主调度循环
│   │   │   └── worker_select.py # Worker 选择算法
│   │   ├── tasks/
│   │   │   ├── bootstrap.py     # Bootstrap 任务
│   │   │   ├── common.py        # 任务通用工具
│   │   │   ├── explore.py       # Explore 任务
│   │   │   └── reason.py        # Reason 任务
│   │   ├── prompts/
│   │   │   ├── default/         # 默认 Prompt 组
│   │   │   └── mock/            # 测试用 Prompt 组
│   │   └── workers/
│   │       ├── base.py          # WorkerDriver 抽象基类
│   │       ├── registry.py      # Worker 注册表
│   │       └── adapters/
│   │           ├── claudecode.py # Claude Code Driver
│   │           ├── codex.py     # Codex CLI Driver
│   │           ├── mock.py      # Mock Driver（测试用）
│   │           └── pi.py        # Pi (通用 API) Driver
│   └── server/
│       ├── app.py               # FastAPI 应用
│       ├── db.py                # SQLite 数据库管理
│       ├── models.py            # Pydantic 请求/响应模型
│       ├── services.py          # 业务逻辑
│       └── routers/
│           ├── export.py        # 图导出
│           ├── hints.py         # Hint CRUD
│           ├── intents.py       # Intent CRUD + 心跳 + 结论
│           ├── projects.py      # 项目 CRUD + Reason Lease
│           └── settings.py      # 运行时配置
├── tests/                       # 测试套件
├── docker-compose.yaml          # 部署编排
├── dispatch.example.yaml        # 配置示例
└── pyproject.toml               # 项目元数据与依赖
```

---

## 10. 依赖与运行环境

| 组件 | 要求 |
|------|------|
| Python | >= 3.12 |
| 数据库 | SQLite（零配置） |
| 容器运行时 | Docker Engine |
| 主要依赖 | FastAPI, uvicorn, click, pyyaml, docker, requests |

运行方式：

```bash
# 启动 Server
cairn serve --host 0.0.0.0 --port 8000

# 启动 Dispatcher
cairn dispatch --config dispatch.yaml

# 仅运行启动健康检查
cairn dispatch --config dispatch.yaml --startup-healthcheck-only

# 单次调度（不循环）
cairn dispatch --config dispatch.yaml --once
```

---

*本文档基于 Cairn v0.2.1 源代码撰写，对应代码库 [Cairn](https://github.com/your-repo/cairn)。*