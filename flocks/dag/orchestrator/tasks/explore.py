"""
Explore 任务执行器 — 执行指定 Intent，产出新 Fact。

支持双阶段：Execute → Conclude Fallback。
"""

import asyncio
from pathlib import Path
from typing import Optional

from flocks.dag.models import IntentEdge, GraphSnapshot, ExploreOutput, FactNode
from flocks.dag.graph import FactIntentGraph
from flocks.dag.orchestrator.contracts import validate_explore_output
from flocks.utils.log import Log

logger = Log.create(service=__name__)
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


async def execute_explore(
    session_manager,
    intent: IntentEdge,
    snapshot: GraphSnapshot,
    goal_content: str,
    config: dict,
    workspace_path: str = "/tmp",
) -> ExploreOutput:
    """
    执行 Explore 任务（含双阶段）：
    Phase 1: 主执行（发送 explore.md Prompt）
    Phase 2: 校验失败 → Conclude Fallback（发送 explore_conclude.md Prompt）
    """
    cfg = config.get("explore", {})
    timeout = cfg.get("timeout", 600)
    conclude_timeout = cfg.get("conclude_timeout", 120)

    source_facts = _build_source_facts_text(intent, snapshot)

    # Phase 1: 主执行
    prompt = _render_explore_prompt(intent, snapshot, goal_content, source_facts)

    session = await session_manager.create(
        directory=workspace_path,
        provider=cfg.get("provider", "anthropic"),
        model=cfg.get("model", "claude-sonnet-4-20250514"),
        tools=cfg.get("tools", ["read", "write", "edit", "bash", "glob", "grep"]),
        temperature=cfg.get("temperature", 0.4),
        system_prompt=prompt,
    )

    try:
        response = await asyncio.wait_for(
            session.send_message(
                "请根据意图描述和出发点，执行探索并输出结论。"
            ),
            timeout=timeout,
        )
        result, is_valid = validate_explore_output(response)

        # Phase 2: Conclude Fallback
        if not is_valid:
            logger.warning("explore.fallback_triggered", {"intent_id": intent.id})
            fallback_prompt = _load_prompt("explore_conclude.md")
            try:
                response = await asyncio.wait_for(
                    session.send_message(fallback_prompt),
                    timeout=conclude_timeout,
                )
                result, is_valid = validate_explore_output(response)
            except asyncio.TimeoutError:
                result = ExploreOutput(
                    new_fact={
                        "id": f"f_fallback_{intent.id}",
                        "content": f"探索超时: {intent.description[:80]}",
                        "confidence": 0.1,
                        "evidence": "任务超时，无有效结论",
                    }
                )
                is_valid = True  # 接受 fallback 结果

        if is_valid:
            logger.info("explore.completed", {"intent_id": intent.id})

    except asyncio.TimeoutError:
        logger.warning("explore.timeout", {"intent_id": intent.id})
        result = ExploreOutput(
            new_fact={
                "id": f"f_timeout_{intent.id}",
                "content": f"探索超时: {intent.description[:80]}",
                "confidence": 0.1,
                "evidence": f"任务在 {timeout}s 后超时",
            }
        )

    await session.close()
    return result


def _render_explore_prompt(
    intent: IntentEdge,
    snapshot: GraphSnapshot,
    goal_content: str,
    source_facts_text: str,
) -> str:
    template = _load_prompt("explore.md")
    graph_yaml = FactIntentGraph.to_yaml(snapshot)

    return template.format(
        goal_content=goal_content,
        intent_description=intent.description,
        source_facts_section=source_facts_text,
        graph_yaml=graph_yaml,
    )


def _build_source_facts_text(intent: IntentEdge, snapshot: GraphSnapshot) -> str:
    """构建来源 Facts 的描述文本"""
    facts_map = {f.id: f for f in snapshot.facts}
    lines = []
    for src_id in intent.source_fact_ids:
        fact = facts_map.get(src_id)
        if fact:
            lines.append(f"- **{src_id}**: {fact.content[:120]}")
        else:
            lines.append(f"- **{src_id}**: (未找到)")
    return "\n".join(lines) if lines else "（无指定出发点）"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
