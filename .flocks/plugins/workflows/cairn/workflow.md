# Cairn 安全事件调查工作流

> 基于 Cairn 黑板架构的三阶段安全事件调查工作流（Bootstrap → Reason↔Explore 循环 → Finalize）。适用于通用安全告警研判场景。

## 适用场景

- 跨设备告警调查（EDR/NDR/Firewall/WAF）
- 威胁情报关联与攻击链还原
- IOC 批量研判与证据收集
- 入侵事件应急响应
- 批量告警降噪（修改 goal 即可）

## 架构

```
Bootstrap(告警初始化) → Loop Check ──continue──→ IR Cycle → Advance ──→ Loop Check
                               │                                    ↑
                               └──exit──→ Finalize(事件报告)           │
                                                                      └── (back)
```

## 节点说明

### 1. Bootstrap（python 节点）
- 自动提取 `alert_id`、`src_ip`、`dst_ip`、`host`、`domain`、`hash`、`url`、`severity` 等字段
- 预置初始 intents：从 IP/域名/Hash 开始情报查询
- 自动设置默认 goal 和 success_criteria（入侵确认 → 攻击路径 → 处置建议）

### 2. Cairn Cycle（logic 节点 — 核心）
**调查方法论** — 遵循标准安全事件处置流程：

| 阶段 | 行为 | 工具示例 |
|------|------|----------|
| **情报查询** | 查询外部 IP、域名、Hash 的威胁情报 | `threatbook_mcp_ip_query`, `threatbook_mcp_domain_query`, `threatbook_mcp_hash_query` |
| **证据关联** | LLM 将新情报与已有 facts 关联 | `llm.ask()` 分析 |
| **推理扩展** | 根据关联结果生成新调查方向 | `web_search`, `threatbook_mcp_web_browsing` |
| **收敛判断** | 攻击链是否完整？证据是否充分？ | LLM 判定 `conclusive` |

**收敛条件**:
- LLM 判定 `conclusive == true`（攻击链清晰、证据充分）
- `iteration >= max_iterations`（默认 25）
- `no_progress_count >= 3`（连续无进展）

### 3. Finalize（llm 节点）
生成结构化安全事件报告，包含：
1. 执行摘要（事件类型 + 风险等级）
2. 证据清单（情报结论 + 攻击链分析）
3. IOC 汇总表
4. 影响评估
5. 应急处置建议
6. 长期加固建议

## 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `origin` | dict | 是 | `{"description": "告警描述", "data_payload": {"alert_id": "...", "src_ip": "...", "dst_ip": "...", "severity": "high"}}` |
| `goal` | string | 否 | 自定义调查目标 |
| `success_criteria` | list[string] | 否 | 自定义成功标准 |
| `max_iterations` | int | 否 | 最大轮次（默认 25） |

## 示例

**单 IP 调查**:
```json
{
  "origin": {
    "description": "发现主机 10.0.0.5 对外部 IP 203.0.113.5 发起异常 TLS 连接",
    "data_payload": {
      "alert_id": "ALERT-2026-001",
      "src_ip": "10.0.0.5",
      "dst_ip": "203.0.113.5",
      "severity": "high"
    }
  }
}
```

**Hash 关联调查**:
```json
{
  "origin": {
    "description": "EDR 告警：主机 win-srv-01 发现可疑文件 hash: a1b2c3d4e5f6...",
    "data_payload": {
      "alert_id": "EDR-100",
      "host": "win-srv-01",
      "hash": "a1b2c3d4e5f678901234567890abcdef",
      "severity": "medium"
    }
  }
}
```