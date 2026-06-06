# Cairn Base — 通用元工作流引擎

> 核心理念：**Define the Origin & Goal, Let the Agent Navigate the State Space.**

## 架构

```
Bootstrap → Loop Check ──continue──→ Cairn Cycle → Advance ──→ Loop Check
                          │                              ↑
                          └──exit──→ Finalize (Report)    │
                                                          └── (back to check)
```

## 节点说明

### 1. Bootstrap（python 节点）
- **职责**: 初始化黑板数据结构
- **输入**: `origin`（起点）、`goal`（目标）、`success_criteria`（成功标准）、`max_iterations`
- **输出**: 初始化的 `facts`、空 `intents` / `completed_intents`、`iteration=0`
- **可修改**: 在子类工作流中重写此节点以做领域特定初始化

### 2. Loop Check（loop 节点）
- **职责**: 根据 `should_continue` 分流
- **`continue`** → 进入下一轮 Cairn Cycle
- **`exit`** → 跳转到 Finalize

### 3. Cairn Cycle（logic 节点 — 核心）
- **职责**: 执行 Reason↔Explore 迭代
- **类型**: `logic` → 由 LLM CodeGen 将长 Prompt 转成可执行 Python
- **行为**:
  - **有 intents → EXPLORE**: 取 `intents[0]`，调用 `tool.run(...)` 执行工具查询，`llm.ask()` 提取事实
  - **无 intents → REASON**: `llm.ask()` 推理下一步，生成新的 intents 或触发收敛
- **收敛条件**:
  - `iteration >= max_iterations`
  - `no_progress_count >= 3`（连续 3 轮无新事实）
  - LLM 判断 `goal_met == true`

### 4. Advance（python 节点）
- **职责**: 迭代计数器自增，透传黑板状态

### 5. Finalize（llm 节点）
- **职责**: 基于 `facts` + `completed_intents` + `final_conclusion` 生成结构化报告

## 数据结构

```
origin: {
  "description": "起点描述",
  "data_payload": { ... }
}
goal: "最终目标"
success_criteria: ["标准1", "标准2"]
facts: [
  { id, type, content, confidence, source }
]
intents: [
  { id, description, required_tool_category, target, priority, rationale, status }
]
```

## 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `origin` | dict | 是 | 任务起点 |
| `goal` | string | 是 | 最终目标 |
| `success_criteria` | list[string] | 否 | 收敛标准 |
| `max_iterations` | int | 否 | 最大循环次数（默认 20） |
| `scenario_hints` | string | 否 | 场景提示文本 |

## 输出

| 输出 | 类型 | 说明 |
|------|------|------|
| `final_report` | string | LLM 生成的报告 Markdown |
| `facts` | list | 最终事实列表 |
| `completed_intents` | list | 已执行意图 |
| `iteration` | int | 总轮次 |