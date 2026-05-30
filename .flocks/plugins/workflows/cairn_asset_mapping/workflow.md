# Cairn 资产测绘工作流

> 基于 Cairn 设计哲学（Bootstrap→Reason↔Explore 循环）的通用资产测绘工作流。通过结构化探索、迭代发现和知识图谱驱动，渐进式发现并绘制资产拓扑。

## 适用场景

- 子域名发现与枚举
- 开放端口与服务探测
- Web 技术栈指纹识别
- IP 与域名关联分析
- 外部暴露面扫描

## 架构

```
Bootstrap(资产初始化) → Loop Check ──continue──→ Asset Mapping Cycle → Advance ──→ Loop Check
                               │                                       ↑
                               └──exit──→ Finalize(资产报告)              │
                                                                         └── (back)
```

## 节点说明

### 1. Bootstrap（python 节点）
- 自动从 `origin.description` 提取目标 IP 或域名
- 预置初始 intents：从根域名开始情报查询
- 自动设置默认 goal 和 success_criteria
- **AI 自动检测**：从自然语言描述中提取目标类型

### 2. Cairn Cycle（logic 节点 — 核心）
- **Phase A** — 有意图时：优先执行 `threatbook_mcp_domain_query` / `threatbook_mcp_ip_query` / `web_search`
- **Phase B** — 无意图时：用 LLM 分析已发现资产，推理下一步探索方向
- **收敛检测**：连续 2 轮无新资产 → `no_progress_count++`，3 次触发收敛

### 3. Finalize（llm 节点）
- 生成结构化资产报告：资产概况 → 清单 → 关系拓扑 → 潜在风险 → 建议

## 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `origin` | dict | 是 | `{"description": "example.com", "data_payload": {"type": "domain", "value": "example.com"}}` |
| `goal` | string | 否 | 自定义目标（默认：发现所有公开资产） |
| `max_iterations` | int | 否 | 最大循环次数（默认 15） |

## 示例

**简单域名测绘**:
```json
{
  "origin": {
    "description": "example.com",
    "data_payload": {"type": "domain", "value": "example.com"}
  }
}
```

**IP 段测绘**:
```json
{
  "origin": {
    "description": "扫描 192.168.1.0/24 的开放端口和服务",
    "data_payload": {"type": "cidr", "value": "192.168.1.0/24"}
  }
}
```