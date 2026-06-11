# Flocks 技术说明文档

> 版本：1.0.0  
> 最后更新：2026-06-11  
> 项目描述：AI 原生 SecOps 平台

---

## 目录

- [Flocks 技术说明文档](#flocks-技术说明文档)
  - [目录](#目录)
  - [1. 项目概述](#1-项目概述)
    - [核心设计理念](#核心设计理念)
  - [2. 系统架构](#2-系统架构)
    - [2.1 总体架构](#21-总体架构)
    - [2.2 模块依赖关系](#22-模块依赖关系)
  - [3. 核心模块详解](#3-核心模块详解)
    - [3.1 Agent 智能体系统](#31-agent-智能体系统)
      - [3.1.1 功能概述](#311-功能概述)
      - [3.1.2 核心数据结构](#312-核心数据结构)
      - [3.1.3 加载机制](#313-加载机制)
      - [3.1.4 委托机制](#314-委托机制)
    - [3.2 会话管理 (Session)](#32-会话管理-session)
      - [3.2.1 功能概述](#321-功能概述)
      - [3.2.2 核心数据结构](#322-核心数据结构)
      - [3.2.3 会话循环](#323-会话循环)
      - [3.2.4 关键特性](#324-关键特性)
    - [3.3 工具系统 (Tool)](#33-工具系统-tool)
      - [3.3.1 功能概述](#331-功能概述)
      - [3.3.2 工具注册](#332-工具注册)
      - [3.3.3 工具分类](#333-工具分类)
      - [3.3.4 工具加载方式](#334-工具加载方式)
      - [3.3.5 工具元数据目录](#335-工具元数据目录)
    - [3.4 AI 模型提供商 (Provider)](#34-ai-模型提供商-provider)
      - [3.4.1 功能概述](#341-功能概述)
      - [3.4.2 支持的提供商](#342-支持的提供商)
      - [3.4.3 核心接口](#343-核心接口)
      - [3.4.4 模型目录](#344-模型目录)
      - [3.4.5 其他 Provider 能力](#345-其他-provider-能力)
    - [3.5 HTTP API 服务 (Server)](#35-http-api-服务-server)
      - [3.5.1 功能概述](#351-功能概述)
      - [3.5.2 路由分类](#352-路由分类)
      - [3.5.3 生命周期管理](#353-生命周期管理)
      - [3.5.4 中间件](#354-中间件)
    - [3.6 CLI 命令行界面](#36-cli-命令行界面)
      - [3.6.1 功能概述](#361-功能概述)
      - [3.6.2 命令结构](#362-命令结构)
      - [3.6.3 服务管理器](#363-服务管理器)
    - [3.7 配置系统 (Config)](#37-配置系统-config)
      - [3.7.1 功能概述](#371-功能概述)
      - [3.7.2 配置层级](#372-配置层级)
      - [3.7.3 核心配置模型](#373-核心配置模型)
      - [3.7.4 API 版本控制](#374-api-版本控制)
    - [3.8 事件总线 (Bus)](#38-事件总线-bus)
      - [3.8.1 功能概述](#381-功能概述)
      - [3.8.2 使用方式](#382-使用方式)
    - [3.9 存储系统 (Storage)](#39-存储系统-storage)
      - [3.9.1 功能概述](#391-功能概述)
      - [3.9.2 核心特性](#392-核心特性)
    - [3.10 内存系统 (Memory)](#310-内存系统-memory)
      - [3.10.1 功能概述](#3101-功能概述)
      - [3.10.2 核心组件](#3102-核心组件)
      - [3.10.3 搜索模式](#3103-搜索模式)
    - [3.11 权限管理 (Permission)](#311-权限管理-permission)
      - [3.11.1 功能概述](#3111-功能概述)
      - [3.11.2 权限级别](#3112-权限级别)
      - [3.11.3 权限检查流程](#3113-权限检查流程)
    - [3.12 MCP 系统](#312-mcp-系统)
      - [3.12.1 功能概述](#3121-功能概述)
      - [3.12.2 组件](#3122-组件)
      - [3.12.3 连接管理](#3123-连接管理)
    - [3.13 LSP 集成](#313-lsp-集成)
      - [3.13.1 功能概述](#3131-功能概述)
      - [3.13.2 语言支持](#3132-语言支持)
      - [3.13.3 能力](#3133-能力)
    - [3.14 工作流引擎 (Workflow)](#314-工作流引擎-workflow)
      - [3.14.1 功能概述](#3141-功能概述)
      - [3.14.2 节点类型](#3142-节点类型)
      - [3.14.3 执行流程](#3143-执行流程)
      - [3.14.4 代码生成](#3144-代码生成)
      - [3.14.5 触发器](#3145-触发器)
    - [3.15 沙箱系统 (Sandbox)](#315-沙箱系统-sandbox)
      - [3.15.1 功能概述](#3151-功能概述)
      - [3.15.2 核心能力](#3152-核心能力)
      - [3.15.3 容器生命周期](#3153-容器生命周期)
    - [3.16 任务调度系统 (Task)](#316-任务调度系统-task)
      - [3.16.1 功能概述](#3161-功能概述)
      - [3.16.2 核心组件](#3162-核心组件)
      - [3.16.3 任务属性](#3163-任务属性)
    - [3.17 钩子系统 (Hooks)](#317-钩子系统-hooks)
      - [3.17.1 功能概述](#3171-功能概述)
      - [3.17.2 生命周期阶段](#3172-生命周期阶段)
      - [3.17.3 失败策略](#3173-失败策略)
    - [3.18 渠道系统 (Channel)](#318-渠道系统-channel)
      - [3.18.1 功能概述](#3181-功能概述)
      - [3.18.2 消息模型](#3182-消息模型)
    - [3.19 认证与授权 (Auth)](#319-认证与授权-auth)
      - [3.19.1 功能概述](#3191-功能概述)
      - [3.19.2 用户模型](#3192-用户模型)
      - [3.19.3 认证流程](#3193-认证流程)
      - [3.19.4 扩展点](#3194-扩展点)
    - [3.20 安全与密钥管理 (Security)](#320-安全与密钥管理-security)
      - [3.20.1 功能概述](#3201-功能概述)
      - [3.20.2 存储格式](#3202-存储格式)
      - [3.20.3 使用方式](#3203-使用方式)
    - [3.21 ACP 协议](#321-acp-协议)
      - [3.21.1 功能概述](#3211-功能概述)
      - [3.21.2 核心能力](#3212-核心能力)
    - [3.22 审计系统 (Audit)](#322-审计系统-audit)
    - [3.23 通知系统 (Notifications)](#323-通知系统-notifications)
      - [3.23.1 功能概述](#3231-功能概述)
      - [3.23.2 通知类型](#3232-通知类型)
      - [3.23.3 本地化](#3233-本地化)
    - [3.24 数据接入 (Ingest)](#324-数据接入-ingest)
      - [3.24.1 功能概述](#3241-功能概述)
      - [3.24.2 Syslog 接入](#3242-syslog-接入)
      - [3.24.3 Kafka 接入](#3243-kafka-接入)
    - [3.25 许可证管理 (License)](#325-许可证管理-license)
    - [3.26 扩展系统 (Extensions)](#326-扩展系统-extensions)
      - [3.26.1 功能概述](#3261-功能概述)
      - [3.26.2 注册函数](#3262-注册函数)
      - [3.26.3 扩展选项](#3263-扩展选项)
    - [3.27 工作区管理 (Workspace)](#327-工作区管理-workspace)
      - [3.27.1 功能概述](#3271-功能概述)
      - [3.27.2 目录结构](#3272-目录结构)
      - [3.27.3 文本预览](#3273-文本预览)
    - [3.28 快照系统 (Snapshot)](#328-快照系统-snapshot)
    - [3.29 项目系统 (Project)](#329-项目系统-project)
      - [3.29.1 功能概述](#3291-功能概述)
      - [3.29.2 项目信息](#3292-项目信息)
      - [3.29.3 VCS 集成](#3293-vcs-集成)
    - [3.30 更新器 (Updater)](#330-更新器-updater)
    - [3.31 浏览器集成 (Browser)](#331-浏览器集成-browser)
      - [3.31.1 功能概述](#3311-功能概述)
      - [3.31.2 组件](#3312-组件)
    - [3.32 插件系统 (Plugin)](#332-插件系统-plugin)
      - [3.32.1 功能概述](#3321-功能概述)
      - [3.32.2 插件类型](#3322-插件类型)
      - [3.32.3 加载机制](#3323-加载机制)
    - [3.33 技能系统 (Skill)](#333-技能系统-skill)
      - [3.33.1 功能概述](#3331-功能概述)
      - [3.33.2 技能操作](#3332-技能操作)
    - [3.34 Hub 系统](#334-hub-系统)
    - [3.35 输入调度 (Input)](#335-输入调度-input)
  - [4. 技术栈](#4-技术栈)
    - [4.1 编程语言与运行时](#41-编程语言与运行时)
    - [4.2 核心依赖](#42-核心依赖)
    - [4.3 AI/ML 依赖](#43-aiml-依赖)
    - [4.4 可选依赖](#44-可选依赖)
  - [5. 部署方式](#5-部署方式)
    - [5.1 终端安装](#51-终端安装)
    - [5.2 Docker 部署](#52-docker-部署)
    - [5.3 服务架构](#53-服务架构)
  - [6. 数据流与关键流程](#6-数据流与关键流程)
    - [6.1 用户请求处理流程](#61-用户请求处理流程)
    - [6.2 Agent 委托流程](#62-agent-委托流程)
    - [6.3 工作流执行流程](#63-工作流执行流程)
    - [6.4 工具调用流程](#64-工具调用流程)
    - [6.5 会话上下文管理](#65-会话上下文管理)

---

## 1. 项目概述

Flocks 是一个 **AI 原生 SecOps（安全运维）平台**，采用 Python 构建，具备多智能体协作、HTTP API 服务与现代化终端用户界面，用于辅助完成各类 SecOps 任务。项目从 TypeScript 版本的 Flocks 移植而来，在保持架构一致性的同时，利用 Python 生态的优势提供了丰富的功能扩展。

### 核心设计理念

- **AI 驱动**：以大语言模型（LLM）为核心驱动力，支持多模型、多提供商
- **模块化架构**：松耦合设计，各模块通过事件总线通信
- **安全优先**：内置权限管理、沙箱执行、密钥加密存储
- **可扩展性**：支持插件、技能、MCP 等多种扩展方式

---

## 2. 系统架构

### 2.1 总体架构

```
┌──────────────────────────────────────────────────────────┐
│                        CLI (Typer)                        │
├──────────────────────────────────────────────────────────┤
│                    HTTP API Server (FastAPI)              │
├──────────────────────────────────────────────────────────┤
│                     Session 管理层                         │
├──────────┬──────────┬──────────┬──────────┬──────────────┤
│  Agent   │   Tool   │ Provider │ Memory   │   Workflow   │
│  系统     │  系统    │  系统    │  系统     │   工作流     │
├──────────┼──────────┼──────────┼──────────┼──────────────┤
│ Sandbox  │  MCP     │  LSP     │  Task    │   Channel    │
│ 沙箱     │  协议    │  集成    │  调度     │   渠道       │
├──────────┴──────────┴──────────┴──────────┴──────────────┤
│                    Bus 事件总线                            │
├──────────────────────────────────────────────────────────┤
│               Storage / SQLite 持久化层                    │
└──────────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

| 模块 | 依赖 | 被依赖 |
|------|------|--------|
| Config | - | 所有模块 |
| Storage | Config | Session, Memory, Task, Auth, 等 |
| Bus | - | Agent, Tool, Server, 等 |
| Agent | Config, Provider, Tool | Session |
| Session | Agent, Provider, Tool, Storage | Server, CLI |
| Provider | Config, Security | Agent, Session |
| Tool | Config, Provider, Security | Agent, Session |
| Permission | Config | Agent, Tool |
| Workflow | Tool, Provider, Storage | Server, CLI |
| Task | Storage, Workflow | Server, CLI |
| MCP | Config, Tool | Server |
| Server | 所有模块 | CLI |

---

## 3. 核心模块详解

### 3.1 Agent 智能体系统

**位置**：`flocks/agent/`  
**核心文件**：`agent.py`, `agent_factory.py`, `registry.py`, `toolset.py`, `prompt_utils.py`

#### 3.1.1 功能概述

Agent 系统是 Flocks 的智能决策核心，负责管理 AI 智能体的生命周期、配置、委托调度和工具暴露。支持多 Agent 协作架构，包括主控 Agent（Orchestrator）和子 Agent（Sub-agent）。

#### 3.1.2 核心数据结构

**AgentInfo**（`agent.py`）：
```python
class AgentInfo(BaseModel):
    name: str                # Agent 唯一标识
    name_cn: Optional[str]   # 中文显示名
    description: str         # 功能描述
    mode: str                # primary | subagent | all
    native: bool             # 是否内置
    hidden: bool             # 是否隐藏
    tools: Optional[List[str]]  # 可用工具列表
    model: Optional[AgentModel] # LLM 模型配置
    prompt: Optional[str]    # 系统提示词
    permission: Ruleset      # 权限规则
    temperature: Optional[float]
    top_p: Optional[float]
```

#### 3.1.3 加载机制

Agent 通过 `agent_factory.py` 中的 YAML 配置加载：

1. **扫描路径**：
   - 内置 Agent：`flocks/agent/agents/<name>/`
   - 项目级插件 Agent：`<cwd>/.flocks/plugins/agents/<name>/`
   - 用户级插件 Agent：`~/.flocks/plugins/agents/<name>/`

2. **配置解析**：
   - `agent.yaml`：静态配置（名称、模型、工具列表、权限）
   - `prompt.md`：静态提示词文件
   - `prompt_builder.py`：动态提示词生成器（通过 `inject()` 函数）

3. **工具解析**：
   - `tools` 字段指定显式工具列表
   - 兼容旧的 `permission` 字段
   - Rex（主控 Agent）默认加载所有内置工具

#### 3.1.4 委托机制

子 Agent 通过 `delegate_task()` 工具调用，由主控 Agent 根据任务域（domain）和触发词（trigger）进行调度：

```python
@dataclass
class DelegationTrigger:
    domain: str    # 任务域
    trigger: str   # 触发词

@dataclass
class AgentPromptMetadata:
    category: str  # 分类
    cost: str      # 开销等级
    triggers: List[DelegationTrigger]
```

| Agent 类型 | 模式 | 用途 |
|---|---|---|
| Rex | primary | 主控协调 Agent |
| Hephaestus | primary | 通用编码/任务 Agent |
| Build | subagent | 构建任务 |
| Plan | subagent | 规划任务 |

---

### 3.2 会话管理 (Session)

**位置**：`flocks/session/`  
**核心文件**：`session.py`, `session_loop.py`, `runner.py`, `message.py`, `prompt.py`

#### 3.2.1 功能概述

会话系统管理 AI 交互的全生命周期，包括会话创建、消息处理、对话循环、上下文压缩、状态管理等功能。

#### 3.2.2 核心数据结构

**SessionInfo**：
```python
class SessionInfo(BaseModel):
    id: str                 # 会话唯一 ID
    project_id: str         # 所属项目
    directory: str          # 工作目录
    title: str              # 会话标题
    agent: Optional[str]    # 关联 Agent
    model: Optional[str]    # 使用的模型
    provider: Optional[str] # 模型提供商
    parent_id: Optional[str] # 父会话（分支）
    owner_user_id: Optional[str]
```

#### 3.2.3 会话循环

`session_loop.py` 实现核心循环逻辑（LoopContext）：

```
1. 获取用户输入
2. 构建提示词（SessionPrompt）
3. 调用 LLM Provider 获取回复
4. 解析工具调用
5. 执行工具（Tool.execute）
6. 处理结果
7. 上下文管理（压缩/清理）
8. 重复 1-7 直到完成
```

#### 3.2.4 关键特性

- **上下文压缩（Compaction）**：当上下文接近模型限制时，自动压缩历史消息
- **分支会话**：支持从现有会话创建子会话分支
- **状态管理**：idle / busy 状态切换，支持中断和恢复
- **消息记录**：完整的消息历史和变更追踪

---

### 3.3 工具系统 (Tool)

**位置**：`flocks/tool/`  
**核心文件**：`registry.py`, `catalog.py`, `tool_loader.py`

#### 3.3.1 功能概述

工具系统是 Agent 与外部世界交互的桥梁，提供统一的工具注册、发现和执行框架。

#### 3.3.2 工具注册

```python
class ToolRegistry:
    @classmethod
    def register(cls, name, fn, ...)  # 注册函数工具
    @classmethod
    def register_function(cls, **kwargs)  # 装饰器注册
    @classmethod
    def execute(cls, name, context, args)  # 执行工具
```

#### 3.3.3 工具分类

| 类别 | 工具示例 | 描述 |
|---|---|---|
| file | read, write, edit, glob, apply_patch, doc_parser | 文件操作 |
| code | bash, grep, lsp | 代码操作 |
| web | webfetch, websearch | 网络操作 |
| system | question, memory_search, memory_write | 系统操作 |
| agent | delegate_task, task, todo | Agent 操作 |
| custom | 用户自定义工具 | 扩展功能 |

#### 3.3.4 工具加载方式

1. **内置工具**：通过 `@ToolRegistry.register_function` 装饰器注册
2. **YAML 工具**：通过 `tool_loader.py` 加载 `_provider.yaml` 配置
   - `handler.type=http`：声明式 HTTP 请求处理器
   - `handler.type=script`：外部 Python 脚本处理器
3. **MCP 工具**：通过 MCP 协议注册
4. **API/Device 工具**：安全设备 API 集成

#### 3.3.5 工具元数据目录

`catalog.py` 维护工具的检索标签和 always_load 标记：

```python
TOOL_TAGS = {
    "read": ["code-reading", "file-inspection"],
    "bash": ["terminal", "command-execution"],
    "delegate_task": ["agent", "delegation"],
    # ... 30+ 工具标签定义
}
```

---

### 3.4 AI 模型提供商 (Provider)

**位置**：`flocks/provider/`  
**核心文件**：`provider.py`,  `sdk/*.py`

#### 3.4.1 功能概述

Provider 系统抽象了不同 AI 模型提供商的 API 差异，提供统一的调用接口。

#### 3.4.2 支持的提供商

| 提供商 | SDK 实现 | 特性 |
|---|---|---|
| OpenAI | `sdk/openai.py` | GPT 系列，工具调用 |
| Anthropic | `sdk/anthropic.py` | Claude 系列 |
| Google | `sdk/google.py` | Gemini 系列 |
| Azure | `sdk/azure.py` | Azure OpenAI |
| DeepSeek | `sdk/deepseek.py` | DeepSeek 系列 |
| Ollama | `sdk/ollama.py` | 本地模型 |
| 更多 | `sdk/*.py` | Groq, Mistral, Cohere, xAI 等 |

#### 3.4.3 核心接口

```python
class BaseProvider:
    async def chat(self, messages, tools, ...) -> ChatResponse
    async def chat_stream(self, messages, tools, ...) -> AsyncIterator[StreamChunk]
```

#### 3.4.4 模型目录

`catalog.json` 定义了所有支持的模型元数据：

```json
{
  "openai-compatible": {
    "name": "OpenAI Compatible",
    "credential_schemas": [...],
    "models": { ... }
  },
  "threatbook-cn-llm": { ... }
}
```

#### 3.4.5 其他 Provider 能力

- **Interleaved**（交错推理）：支持 reasoning_details 与 tool_calls 交替输出
- **凭证管理**：支持 API Key、Base URL 等多种认证方式
- **环境变量回退**：支持 `LLM_API_KEY`、`LLM_API_BASE` 等标准环境变量

---

### 3.5 HTTP API 服务 (Server)

**位置**：`flocks/server/`  
**核心文件**：`app.py`, `routes/*.py`

#### 3.5.1 功能概述

基于 FastAPI 构建的高性能 HTTP API 服务，提供 RESTful 接口供 WebUI、TUI 和外部系统调用。

#### 3.5.2 路由分类

| 路由模块 | 功能 |
|---|---|
| `routes/agent.py` | Agent 管理（CRUD、配置） |
| `routes/session.py` | 会话管理 |
| `routes/message.py` | 消息处理 |
| `routes/tool.py` | 工具执行 |
| `routes/mcp.py` | MCP 管理 |
| `routes/health.py` | 健康检查 |
| `routes/auth.py` | 认证 |
| `routes/config.py` | 配置管理 |
| `routes/event.py` | 事件推送（SSE） |
| `routes/file.py` | 文件操作 |
| `routes/model.py` | 模型管理 |
| `routes/hub.py` | Hub 管理 |
| `routes/lsp.py` | LSP 集成 |
| `routes/vcs.py` | 版本控制 |
| `routes/project.py` | 项目管理 |
| `routes/pty.py` | PTY 终端 |
| `routes/logs.py` | 日志查看 |

#### 3.5.3 生命周期管理

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动阶段
    await run_startup_phase("updater.cleanup")
    await run_startup_phase("observability.init")
    await run_startup_phase("storage.init")
    await run_startup_phase("auth.init")
    # ...
    yield
    # 关闭阶段
    await shutdown_observability()
```

#### 3.5.4 中间件

- CORS 中间件（跨域支持）
- 认证中间件（`apply_auth_for_request`）
- 请求日志中间件
- 错误处理中间件

---

### 3.6 CLI 命令行界面

**位置**：`flocks/cli/`  
**核心文件**：`main.py`, `commands/*.py`

#### 3.6.1 功能概述

基于 Typer 构建的命令行界面，提供服务管理、会话控制、工具调用等功能。

#### 3.6.2 命令结构

```
flocks
├── start          # 启动所有服务
├── stop           # 停止所有服务
├── restart        # 重启所有服务
├── status         # 查看服务状态
├── logs           # 查看日志
├── session        # 会话管理
│   ├── list
│   ├── create
│   └── delete
├── mcp            # MCP 管理
├── export         # 数据导出
├── import         # 数据导入
├── stats          # 统计信息
├── task           # 任务管理
├── skills         # 技能管理
├── admin          # 管理命令
├── update         # 更新
├── browser        # 浏览器控制
└── tui            # 终端 UI
```

#### 3.6.3 服务管理器

`service_manager.py` 负责：
- 服务进程的启动/停止/重启
- WebUI 构建管理
- 端口配置
- 守护进程模式
- 运行时记录持久化

---

### 3.7 配置系统 (Config)

**位置**：`flocks/config/`  
**核心文件**：`config.py`, `config_writer.py`, `api_versioning.py`

#### 3.7.1 功能概述

统一的配置管理，兼容 TypeScript 版本的配置格式，支持 JSON/YAML 配置文件和 Pydantic 配置模型。

#### 3.7.2 配置层级

1. **默认配置**：代码内嵌默认值
2. **配置文件**：`~/.flocks/config/flocks.json`
3. **环境变量**：`FLOCKS_*` 前缀
4. **命令行参数**：CLI 传入

#### 3.7.3 核心配置模型

```python
class PermissionConfig:
    read/edit/glob/grep/bash/task: PermissionRule
    todo/question/webfetch/websearch: PermissionAction

class AgentConfig:
    name, model, temperature, top_p, tools, permission, ...
```

#### 3.7.4 API 版本控制

`api_versioning.py` 管理 API 的向后兼容性，在模式变更时自动迁移配置。

---

### 3.8 事件总线 (Bus)

**位置**：`flocks/bus/`  
**核心文件**：`bus.py`, `bus_event.py`, `events.py`

#### 3.8.1 功能概述

发布-订阅模式的事件总线，实现模块间解耦通信。

#### 3.8.2 使用方式

```python
# 定义事件
SessionCreated = BusEvent.define("session.created", SessionCreatedProps)

# 订阅
Bus.subscribe(SessionCreated, on_session_created)

# 发布
await Bus.publish(SessionCreated, {"session_id": "abc123"})
```

---

### 3.9 存储系统 (Storage)

**位置**：`flocks/storage/`  
**核心文件**：`storage.py`

#### 3.9.1 功能概述

基于 SQLite（通过 `aiosqlite`）的持久化存储系统，支持 WAL 模式、JSON 序列化、Pydantic 模型存取。

#### 3.9.2 核心特性

- **异步 SQLite**：基于 `aiosqlite` 的异步访问
- **Pydantic 集成**：自动序列化/反序列化
- **WAL 模式**：提高并发读写性能
- **键值结构**：兼容 TypeScript 版本的层级键访问
- **向量存储**：`vector.py` 提供向量相似度搜索

---

### 3.10 内存系统 (Memory)

**位置**：`flocks/memory/`  
**核心文件**：`manager.py`, `search/hybrid.py`, `sync/indexer.py`

#### 3.10.1 功能概述

为 Agent 提供长期记忆能力，包括文件索引、混合搜索（向量 + 关键词）、记忆同步。

#### 3.10.2 核心组件

| 组件 | 功能 |
|---|---|
| MemoryManager | 内存系统编排器（单例） |
| HybridSearch | 混合搜索（向量嵌入 + BM25 关键词） |
| MemoryIndexer | 文件索引器 |
| MemoryConfig | 嵌入模型配置 |

#### 3.10.3 搜索模式

- **向量搜索**：使用 LLM 嵌入模型进行语义搜索
- **关键词搜索**：BM25 算法进行精确匹配
- **混合搜索**：两种结果加权融合

---

### 3.11 权限管理 (Permission)

**位置**：`flocks/permission/`  
**核心文件**：`manager.py`, `rule.py`, `helpers.py`

#### 3.11.1 功能概述

控制 Agent 对工具和资源的访问权限，支持自动批准、拒绝和询问三种模式。

#### 3.11.2 权限级别

| 级别 | 行为 |
|---|---|
| ALLOW | 自动允许 |
| DENY | 自动拒绝 |
| ASK | 询问用户 |

#### 3.11.3 权限检查流程

```
PermissionRequest(tool, path)
  → 检查已拒绝缓存 → 拒绝
  → 检查已批准缓存 → 允许
  → 遍历规则列表匹配
    → ALLOW → 允许
    → DENY → 拒绝
    → 无匹配 → ASK 用户
```

---

### 3.12 MCP 系统

**位置**：`flocks/mcp/`  
**核心文件**：`server.py`, `client.py`, `registry.py`, `adapter.py`

#### 3.12.1 功能概述

Model Context Protocol 实现，支持与外部 MCP 服务器通信，发现和注册远程工具。

#### 3.12.2 组件

| 组件 | 功能 |
|---|---|
| McpServerManager | MCP 服务器生命周期管理 |
| McpClient | MCP 协议客户端 |
| McpToolRegistry | MCP 工具注册表 |
| McpToolAdapter | MCP 工具适配器 |

#### 3.12.3 连接管理

- 支持本地和远程 MCP 服务器
- 自动重连与指数退避
- 工具注册同步
- 凭证安全解析（`{secret:xxx}` 引用）

---

### 3.13 LSP 集成

**位置**：`flocks/lsp/`  
**核心文件**：`server.py`, `client.py`, `language.py`

#### 3.13.1 功能概述

语言服务器协议（LSP）集成，为 Agent 提供代码导航、自动补全、诊断等代码智能能力。

#### 3.13.2 语言支持

| 语言 | LSP 服务器 |
|---|---|
| Python | pyright / pylsp |
| TypeScript | typescript-language-server |
| Go | gopls |
| Rust | rust-analyzer |

#### 3.13.3 能力

- 项目根目录自动发现
- LSP 进程生命周期管理
- 代码补全、跳转定义、引用查找
- 诊断信息获取

---

### 3.14 工作流引擎 (Workflow)

**位置**：`flocks/workflow/`  
**核心文件**：`engine.py`, `models.py`, `runner.py`, `compiler.py`

#### 3.14.1 功能概述

可编程的工作流执行引擎，支持 Python 脚本节点、逻辑分支、循环、工具调用、LLM 调用、HTTP 请求和子工作流。

#### 3.14.2 节点类型

| 节点类型 | 说明 |
|---|---|
| `python` | 执行 Python 代码 |
| `logic` | 逻辑判断与分支 |
| `branch` | 条件分支 |
| `loop` | 循环执行 |
| `tool` | 调用系统工具 |
| `llm` | 调用 LLM |
| `http_request` | HTTP 请求 |
| `subworkflow` | 嵌套子工作流 |

#### 3.14.3 执行流程

```
Workflow(start_node)
  → 拓扑排序节点
  → 批次执行（依赖解析）
  → 节点间数据传递（Edge.mapping）
  → 结果聚合
  → 返回 ExecutionResult
```

#### 3.14.4 代码生成

- `SimpleCodeGen`：基于模板的代码生成
- `LLMCodeGen`：基于 LLM 的代码生成

#### 3.14.5 触发器

工作流支持多种触发器启动方式：
- Syslog 消息触发
- 定时调度（Cron）
- 事件驱动触发

---

### 3.15 沙箱系统 (Sandbox)

**位置**：`flocks/sandbox/`  
**核心文件**：`docker.py`, `config.py`, `registry.py`, `workspace.py`

#### 3.15.1 功能概述

为 Agent 提供隔离的 Docker 沙箱执行环境，确保命令执行的安全性。

#### 3.15.2 核心能力

- **Docker CLI 管理**：通过 `docker` CLI 命令管理容器
- **镜像管理**：自动拉取和缓存沙箱镜像
- **配置哈希**：基于配置的哈希值复用容器
- **工作空间挂载**：宿主机工作空间挂载到容器
- **环境安全**：环境变量过滤和安全策略

#### 3.15.3 容器生命周期

```
ensure_image → create_container → start_container
  → exec_command → stop_container → remove_container
```

---

### 3.16 任务调度系统 (Task)

**位置**：`flocks/task/`  
**核心文件**：`manager.py`, `queue.py`, `scheduler.py`, `executor.py`, `store.py`

#### 3.16.1 功能概述

提供后台任务调度和执行能力，支持定时任务、重试、队列管理、并发控制。

#### 3.16.2 核心组件

| 组件 | 功能 |
|---|---|
| TaskManager | 任务管理器（单例） |
| TaskQueue | 任务队列（并发控制） |
| TaskScheduler | 定时调度器 |
| TaskExecutor | 任务执行器 |
| TaskStore | 任务持久化 |

#### 3.16.3 任务属性

```python
class TaskScheduler:
    name, title, mode, trigger, workflow_id
    retry_config, priority, timeout, ...
```

- **调度模式**：once, interval, cron, manual
- **触发类型**：manual, cron, syslog, webhook
- **优先级**：low, normal, high, critical

---

### 3.17 钩子系统 (Hooks)

**位置**：`flocks/hooks/`  
**核心文件**：`pipeline.py`, `registry.py`, `types.py`

#### 3.17.1 功能概述

提供轻量级 Hook 注册和执行管道，在特定生命周期阶段插入自定义逻辑。

#### 3.17.2 生命周期阶段

| 阶段 | 触发时机 |
|---|---|
| chat.message | 聊天消息处理 |
| llm.call.before | LLM 调用前 |
| llm.call.after | LLM 调用后 |
| tool.execute.before | 工具执行前 |
| tool.execute.after | 工具执行后 |
| event | 事件触发 |
| channel.inbound | 渠道入站消息 |
| channel.outbound.before/after | 渠道出站消息 |

#### 3.17.3 失败策略

- `isolate`：失败不影响调用者
- `propagate`：失败传递
- `fail_closed`：失败关闭

---

### 3.18 渠道系统 (Channel)

**位置**：`flocks/channel/`  
**核心文件**：`base.py`, `registry.py`

#### 3.18.1 功能概述

提供多渠道消息通信能力，支持 IM、邮件等外部平台集成。

#### 3.18.2 消息模型

```python
@dataclass
class InboundMessage:
    channel_id, account_id, message_id, sender_id
    chat_type: ChatType  # direct | group | channel
    text, media_url, reply_to_id, thread_id, ...

@dataclass
class OutboundContext:
    channel_id, to, text, media_url, format_hint, ...
```

---

### 3.19 认证与授权 (Auth)

**位置**：`flocks/auth/`  
**核心文件**：`service.py`, `backend.py`, `context.py`, `local.py`

#### 3.19.1 功能概述

提供本地账号认证和授权管理，基于 SQLite 存储用户信息。

#### 3.19.2 用户模型

```python
class LocalUser:
    id, username, role, status
    must_reset_password, created_at, last_login_at
```

#### 3.19.3 认证流程

1. 密码哈希（HMAC-SHA256）
2. 会话 Token（URL-safe 随机字符串）
3. Session TTL：7 天
4. 临时密码 TTL：24 小时

#### 3.19.4 扩展点

- `register_auth_backend()`：注册自定义认证后端
- 支持 SSO/OAuth 扩展

---

### 3.20 安全与密钥管理 (Security)

**位置**：`flocks/security/`  
**核心文件**：`secrets.py`

#### 3.20.1 功能概述

简单的扁平 KV 密钥管理，使用 JSON 文件存储所有敏感信息。

#### 3.20.2 存储格式

- 文件位置：`~/.flocks/config/.secret.json`
- 命名规范：`{provider_id}_llm_key`, `{service_id}_api_key`, `{server_name}_mcp_key`

#### 3.20.3 使用方式

```python
secrets = SecretManager()
secrets.set("anthropic_llm_key", "sk-xxx")
api_key = secrets.get("anthropic_llm_key")
```

---

### 3.21 ACP 协议

**位置**：`flocks/acp/`  
**核心文件**：`agent.py`, `session.py`, `types.py`

#### 3.21.1 功能概述

Agent Client Protocol 实现，为编辑器（如 Zed）提供 Agent 集成接口。

#### 3.21.2 核心能力

- Agent 初始化与能力声明
- 会话管理
- 工具调用
- MCP 服务器配置
- **工具类型映射**：
  - `bash` → execute
  - `webfetch` → fetch
  - `edit/write` → edit
  - `grep/glob` → search
  - `read/list` → read

---

### 3.22 审计系统 (Audit)

**位置**：`flocks/audit/`

通过 `register_audit_sink()` 扩展点注册审计接收器，记录所有安全相关操作。

---

### 3.23 通知系统 (Notifications)

**位置**：`flocks/notifications/`  
**核心文件**：`service.py`

#### 3.23.1 功能概述

向用户展示通知消息，支持多种通知类型和本地化内容。

#### 3.23.2 通知类型

| 类型 | 用途 |
|---|---|
| benefit | 功能优势说明 |
| whats_new | 新功能发布 |
| announcement | 公告通知 |

#### 3.23.3 本地化

- 支持中英文双语内容（`zh-CN` / `en-US`）
- 基于 RFC 5646 语言标签

---

### 3.24 数据接入 (Ingest)

**位置**：`flocks/ingest/`  
**核心文件**：`syslog/manager.py`, `syslog/parser.py`, `kafka/manager.py`

#### 3.24.1 功能概述

提供外部数据接入能力，支持 Syslog 和 Kafka 协议。

#### 3.24.2 Syslog 接入

- **支持协议**：TCP / UDP
- **工作流触发**：收到 Syslog 消息后触发工作流执行
- **并发控制**：每工作流最多 8 个并发执行
- **队列缓冲**：每工作流最多 1000 条缓冲

#### 3.24.3 Kafka 接入

- 消费者组管理
- 自动提交偏移量
- 消息路由到工作流

---

### 3.25 许可证管理 (License)

**位置**：`flocks/license/`

通过 `register_license_checker()` 扩展点注册许可证校验器，支持商业版功能控制。

---

### 3.26 扩展系统 (Extensions)

**位置**：`flocks/extensions.py`

#### 3.26.1 功能概述

为 OSS 和 Pro 版本提供统一的扩展注册语义。

#### 3.26.2 注册函数

```python
register_auth_backend(backend)     # 注册认证后端
register_license_checker(checker)   # 注册许可证校验
register_audit_sink(sink)           # 注册审计接收器
register_http_hook(hook, ...)       # 注册 HTTP Hook
```

#### 3.26.3 扩展选项

```python
@dataclass(frozen=True)
class ExtensionOptions:
    name: str
    priority: int = 100
    timeout_seconds: Optional[float] = None
    fail_policy: FailPolicy = FailPolicy.ISOLATE
```

---

### 3.27 工作区管理 (Workspace)

**位置**：`flocks/workspace/`  
**核心文件**：`manager.py`, `models.py`

#### 3.27.1 功能概述

管理 `~/.flocks/workspace/` 目录，提供用户可见的文件存储和预览能力。

#### 3.27.2 目录结构

```
~/.flocks/workspace/
├── outputs/     # Agent 生成的输出文件
├── knowledge/   # 用户知识库
├── users/       # 用户文件
└── shared/      # 共享文件
```

#### 3.27.3 文本预览

支持多种文本格式的 WebUI 预览（`.md`, `.txt`, `.json`, `.py`, `.js`, `.yaml` 等）。

---

### 3.28 快照系统 (Snapshot)

**位置**：`flocks/snapshot/`  
**核心文件**：`snapshot.py`

提供会话快照功能，用于回滚和恢复会话状态。

---

### 3.29 项目系统 (Project)

**位置**：`flocks/project/`  
**核心文件**：`project.py`, `instance.py`, `bootstrap.py`, `vcs.py`

#### 3.29.1 功能概述

管理项目生命周期，包括项目发现、元数据管理和版本控制集成。

#### 3.29.2 项目信息

```python
class ProjectInfo:
    id: str           # 项目 ID（基于 Git 远程或目录路径）
    worktree: str     # 工作目录
    vcs: Optional[str] # 版本控制系统类型
    name: Optional[str] # 项目名称
    sandboxes: List[str] # 关联沙箱列表
```

#### 3.29.3 VCS 集成

- Git 分支管理
- Diff/Status 查询
- 提交历史查看

---

### 3.30 更新器 (Updater)

**位置**：`flocks/updater/`  
**核心文件**：`updater.py`, `deploy.py`, `models.py`

提供自动更新能力，包括版本检查、部署清理、CLI 入口刷新。

---

### 3.31 浏览器集成 (Browser)

**位置**：`flocks/browser/`  
**核心文件**：`run.py`, `daemon.py`, `admin.py`, `_ipc.py`

#### 3.31.1 功能概述

基于 Chrome DevTools Protocol (CDP) 的浏览器自动化控制。

#### 3.31.2 组件

| 组件 | 功能 |
|---|---|
| `run.py` | 浏览器启动入口 |
| `daemon.py` | 浏览器守护进程 |
| `admin.py` | 浏览器管理 |
| `_ipc.py` | IPC 通信 |
| `helpers.py` | 辅助函数 |
| `utils.py` | 工具函数 |

---

### 3.32 插件系统 (Plugin)

**位置**：`flocks/plugin/`  
**核心文件**：`loader.py`

#### 3.32.1 功能概述

提供插件加载框架，支持 Agent、工具、MCP 等扩展点的动态加载。

#### 3.32.2 插件类型

| 类型 | 描述 |
|---|---|
| Agent 插件 | `~/.flocks/plugins/agents/<name>/` |
| 工具插件 | `~/.flocks/plugins/tools/<name>/` |
| MCP 插件 | 通过 MCP 协议注册的服务器 |

#### 3.32.3 加载机制

1. 扫描插件目录
2. 解析 YAML 配置
3. 注册到对应系统（Agent/Tool/MCP）

---

### 3.33 技能系统 (Skill)

**位置**：`flocks/skill/`  
**核心文件**：`skill.py`, `installer.py`

#### 3.33.1 功能概述

管理 Agent 技能（预定义的知识包），提供安装、查询和加载能力。

#### 3.33.2 技能操作

- `flocks_skills find`：查找可用技能
- `flocks_skills install`：安装技能
- `flocks_skills status`：查看状态
- `flocks_skills install-deps`：安装依赖
- `skill_load`：加载技能到会话

---

### 3.34 Hub 系统

**位置**：`flocks/hub/`  
**核心文件**：`catalog.py`, `installer.py`, `local.py`, `security.py`

提供在线/本地资源目录管理，支持技能、插件、工具的分发和安装。

---

### 3.35 输入调度 (Input)

**位置**：`flocks/input/`  
**核心文件**：`dispatcher.py`, `types.py`, `events.py`, `output.py`

管理用户输入的分发和处理，包括消息类型定义和输出格式化。

---

## 4. 技术栈

### 4.1 编程语言与运行时

| 技术 | 用途 |
|---|---|
| Python 3.10+ | 主要开发语言 |
| Node.js / npm | WebUI 构建 |
| Bun | TUI 运行时（可选） |

### 4.2 核心依赖

| 库 | 用途 |
|---|---|
| FastAPI | HTTP API 框架 |
| Typer | CLI 框架 |
| Pydantic | 数据验证与配置 |
| Pydantic-Settings | 配置管理 |
| aiosqlite | 异步 SQLite 访问 |
| Rich | 终端格式化输出 |
| httpx | HTTP 客户端 |
| PyYAML | YAML 解析 |
| python-dotenv | 环境变量加载 |

### 4.3 AI/ML 依赖

| 库 | 用途 |
|---|---|
| openai | OpenAI API 客户端 |
| anthropic | Anthropic API 客户端 |
| google-genai | Google AI API 客户端 |

### 4.4 可选依赖

| 库 | 用途 |
|---|---|
| docker | Docker SDK（沙箱） |
| openpyxl | Excel 导出 |
| kafka-python | Kafka 接入 |

---

## 5. 部署方式

### 5.1 终端安装

```bash
# macOS/Linux
curl -fsSL https://gitee.com/flocks/flocks/raw/main/install_zh.sh | bash

# Windows (PowerShell Administrator)
powershell -c "irm https://gitee.com/flocks/flocks/raw/main/install_zh.ps1 | iex"
```

### 5.2 Docker 部署

```bash
docker pull ghcr.io/agentflocks/flocks:latest
docker run -d \
  --name flocks \
  -p 8000:8000 \
  -p 5173:5173 \
  --shm-size 4gb \
  -v "${HOME}/.flocks:/home/flocks/.flocks" \
  ghcr.io/agentflocks/flocks:latest
```

### 5.3 服务架构

```
┌──────────────────────┐     ┌──────────────────────┐
│   FastAPI Server      │     │   WebUI (Vite/React)  │
│   :8000               │◄───►│   :5173               │
│                      │     │                      │
│   AI Provider API    │     │   TUI (Terminal)     │
│   MCP Server         │     │                      │
│   SQLite Storage     │     │                      │
└──────────────────────┘     └──────────────────────┘
```

---

## 6. 数据流与关键流程

### 6.1 用户请求处理流程

```
User Input → CLI/WebUI/TUI
  → Server (FastAPI)
    → Session (会话管理)
      → Agent (智能体)
        → Provider (LLM 调用)
          → Chat Response
            → Tool Calls (工具执行)
              → Final Response
```

### 6.2 Agent 委托流程

```
User: "分析这个病毒样本"
  → Rex Agent (主控)
    → 解析任务域: malware_analysis
    → 匹配委托触发器
    → delegate_task("malware_analysis", ...)
      → Malware Analysis Sub-agent
        → 加载对应技能
        → 执行分析工具
        → 返回分析结果
  → Rex 汇总结果 → 返回用户
```

### 6.3 工作流执行流程

```
Trigger (syslog/cron/manual)
  → Workflow Engine
    → 拓扑排序节点
    → 按批次执行
      → Python 节点: 执行代码
      → LLM 节点: 调用 Provider
      → Tool 节点: 执行系统工具
      → Branch 节点: 条件判断
    → 数据传递 (Edge Mapping)
    → 结果聚合
    → 返回 ExecutionResult
```

### 6.4 工具调用流程

```
Agent 决定调用工具
  → ToolRegistry.execute(name, context, args)
    → PermissionManager.check(request)
      → ALLOW → 执行
      → DENY  → 拒绝
      → ASK   → 询问用户
    → 执行 Handler
    → 返回 ToolResult
```

### 6.5 会话上下文管理

```
会话开始 → 创建 SessionInfo
  → 逐步累积消息
  → 上下文大小接近限制阈值
    → SessionCompaction
      → 策略评估 (CompactionPolicy)
      → 历史压缩 (build_compaction_history)
      → 重新构建上下文
  → 继续执行
会话结束 → 持久化到 Storage
```

---

> 本文档基于 Flocks 项目 v1.0.0 源码生成，涵盖了所有核心模块的功能描述、数据结构和关键流程。随着项目的持续开发，本文档可能需要相应更新。