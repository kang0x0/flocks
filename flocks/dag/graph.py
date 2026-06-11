"""
DAG 图操作工具 — Mermaid 导出、YAML 导出、路径查找、进度计算。
"""

from collections import deque
from typing import List, Optional

from flocks.dag.models import GraphSnapshot, FactNode


class FactIntentGraph:
    """Fact-Intent 图操作（纯函数，无状态）"""

    # ================================================================
    # Mermaid 导出（WebUI 图可视化）
    # ================================================================

    @staticmethod
    def to_mermaid(snapshot: GraphSnapshot) -> str:
        """生成 Mermaid flowchart LR 源码"""
        lines = ["graph LR"]

        # 节点定义
        for fact in snapshot.facts:
            label = FactIntentGraph._fact_label(fact)
            shape = f'(["{label}"])' if fact.fact_type in ("origin", "goal") else f'["{label}"]'
            lines.append(f"    {fact.id}{shape}")

        for intent in snapshot.all_intents:
            label = FactIntentGraph._intent_label(intent)
            lines.append(f'    {intent.id}["{label}"]')

        # 边：source_facts → intent → result_fact
        intent_by_id = {i.id: i for i in snapshot.all_intents}
        for fact in snapshot.facts:
            if not fact.source_intent_id:
                continue
            intent = intent_by_id.get(fact.source_intent_id)
            if intent is None:
                continue
            lines.append(f'    {intent.id} -->|产出| {fact.id}')

        for intent in snapshot.all_intents:
            for src_id in intent.source_fact_ids:
                short_desc = intent.description[:20].replace('"', "'")
                lines.append(f'    {src_id} -->|"{short_desc}"| {intent.id}')

        # 样式
        lines.append(FactIntentGraph._mermaid_styles(snapshot))

        return "\n".join(lines)

    @staticmethod
    def _fact_label(fact: FactNode) -> str:
        content = fact.content[:50].replace('"', "'").replace("<br/>", " ")
        return f"{fact.id}<br/>{content}"

    @staticmethod
    def _intent_label(intent) -> str:
        desc = intent.description[:40].replace('"', "'")
        status_mark = {"open": "○", "claimed": "◐", "completed": "●", "failed": "✗"}.get(
            intent.status, "?"
        )
        return f"{status_mark} {intent.id}<br/>{desc}"

    @staticmethod
    def _mermaid_styles(snapshot: GraphSnapshot) -> str:
        styles = []
        # 起点/终点节点
        styles.append("    style origin fill:#e8f5e9,stroke:#2e7d32")
        styles.append("    style goal fill:#fff3e0,stroke:#ef6c00")
        # Fact 节点
        for fact in snapshot.facts:
            if fact.fact_type in ("origin", "goal"):
                continue
            styles.append(f"    style {fact.id} fill:#e3f2fd,stroke:#1565c0")
        # Intent 节点（按状态着色）
        for intent in snapshot.all_intents:
            color = {
                "open": ("#fff8e1,stroke:#f9a825"),
                "claimed": ("#e8eaf6,stroke:#3949ab"),
                "completed": ("#e8f5e9,stroke:#2e7d32"),
                "failed": ("#ffebee,stroke:#c62828"),
            }.get(intent.status, ("#f5f5f5,stroke:#9e9e9e"))
            styles.append(f"    style {intent.id} fill:{color}")
        return "\n".join(styles)

    # ================================================================
    # YAML 导出（Agent Prompt 注入）
    # ================================================================

    @staticmethod
    def to_yaml(snapshot: GraphSnapshot) -> str:
        """生成图结构的 YAML 文本（注入 Agent Prompt）"""
        lines = [
            f"project: {snapshot.project_title}",
            f"status: {snapshot.status.value}",
            "",
            "facts:",
        ]
        for fact in snapshot.facts:
            lines.append(f"  - id: {fact.id}")
            lines.append(f"    type: {fact.fact_type}")
            lines.append(f'    content: "{fact.content[:100]}"')
            if fact.confidence < 1.0:
                lines.append(f"    confidence: {fact.confidence}")

        lines.append("")
        lines.append("intents:")
        for intent in snapshot.all_intents:
            lines.append(f"  - id: {intent.id}")
            lines.append(f"    status: {intent.status.value}")
            lines.append(f'    description: "{intent.description[:100]}"')
            if intent.source_fact_ids:
                lines.append(f"    from: [{', '.join(intent.source_fact_ids)}]")
            if intent.result_fact_id:
                lines.append(f"    result: {intent.result_fact_id}")

        if snapshot.unread_hints:
            lines.append("")
            lines.append("unread_hints:")
            for hint in snapshot.unread_hints:
                lines.append(f"  - {hint[:100]}")

        if snapshot.statistics:
            lines.append("")
            lines.append("statistics:")
            for k, v in snapshot.statistics.items():
                lines.append(f"  {k}: {v}")

        return "\n".join(lines)

    # ================================================================
    # 路径查找
    # ================================================================

    @staticmethod
    def find_paths_to_goal(snapshot: GraphSnapshot, max_paths: int = 10) -> List[List[str]]:
        """BFS 查找从 origin 到 goal 的所有路径"""
        intent_by_id = {i.id: i for i in snapshot.all_intents}
        fact_ids = {f.id for f in snapshot.facts}

        # 构建邻接表: fact -> [intent] -> [fact]
        adj: dict = {fid: [] for fid in fact_ids}
        for intent in snapshot.all_intents:
            if intent.result_fact_id and intent.result_fact_id in fact_ids:
                for src_id in intent.source_fact_ids:
                    if src_id in adj:
                        adj[src_id].append((intent.id, intent.result_fact_id))

        paths: List[List[str]] = []
        queue = deque()
        queue.append(("origin", ["origin"]))
        visited_in_path = set()

        while queue and len(paths) < max_paths:
            current, path = queue.popleft()
            if current == "goal":
                paths.append(path)
                continue
            for intent_id, next_fact in adj.get(current, []):
                if next_fact not in path:
                    queue.append((next_fact, path + [intent_id, next_fact]))

        return paths

    # ================================================================
    # 前沿分析
    # ================================================================

    @staticmethod
    def find_frontier_facts(snapshot: GraphSnapshot) -> List[FactNode]:
        """找出尚无 Intent 指出的前沿 Facts（探索前沿）"""
        fact_ids_with_outgoing = set()
        for intent in snapshot.all_intents:
            if intent.status in ("open", "claimed"):
                for src_id in intent.source_fact_ids:
                    fact_ids_with_outgoing.add(src_id)

        frontier = [
            f for f in snapshot.facts
            if f.id not in ("goal",) and f.id not in fact_ids_with_outgoing
        ]
        return frontier

    # ================================================================
    # 进度估算
    # ================================================================

    @staticmethod
    def compute_progress(snapshot: GraphSnapshot) -> float:
        """简单进度估算：完成的 Intent 占比，并结合路径信息"""
        total = len(snapshot.all_intents)
        if total == 0:
            return 0.0
        completed = sum(1 for i in snapshot.all_intents if i.status == "completed")
        if snapshot.status.value == "completed":
            return 1.0
        return min(0.99, completed / max(total, 1))
