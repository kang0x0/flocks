"""
Reason 任务执行器 — 读图推理，提出新 Intent 或声明完成。
"""

from pathlib import Path
from typing import Optional

from flocks.dag.models import GraphSnapshot, ReasonOutput, FactNode
from flocks.dag.graph import FactIntentGraph
from flocks.dag.orchestrator.contracts import validate_reason_output
from flocks.utils.log import Log

logger = Log.create(service=__name__)
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


async def execute_reason(
    session_manager,
    snapshot: GraphSnapshot,
    goal_content: str,
    max_intents: int,
    config: dict,
    workspace_path: str = "/tmp",
) -> ReasonOutput:
    """
    执行 Reason 任务：
    1. 渲染 reason.md Prompt（含完整图快照）
    2. 创建 Session → send_message → ReAct 循环
    3. 返回 ReasonOutput（含 new_intents 或 complete 声明）
    """
    prompt = _render_reason_prompt(snapshot, goal_content, max_intents)
    cfg = config.get("reason", {})

    session = await session_manager.create(
        directory=workspace_path,
        provider=cfg.get("provider", "openai"),
        model=cfg.get("model", "gpt-4o"),
        tools=cfg.get("tools", ["read", "glob", "grep"]),
        temperature=cfg.get("temperature", 0.2),
        system_prompt=prompt,
    )

    response = await session.send_message(
        "请根据系统提示词中的图状态，分析当前态势并决定下一步。"
    )

    output, is_valid = validate_reason_output(response)
    if is_valid:
        logger.info("reason.completed", {
            "complete": output.complete,
            "intents_count": len(output.new_intents),
        })
    else:
        logger.warning("reason.invalid_output", {"output_snippet": response[:200]})

    await session.close()
    return output


def _render_reason_prompt(
    snapshot: GraphSnapshot,
    goal_content: str,
    max_intents: int,
) -> str:
    """渲染 reason.md 模板"""
    template = _load_prompt("reason.md")

    graph_yaml = FactIntentGraph.to_yaml(snapshot)
    hints = "\n".join(f"- {h}" for h in snapshot.unread_hints) if snapshot.unread_hints else "（无未读提示）"

    return template.format(
        goal_content=goal_content,
        graph_yaml=graph_yaml,
        hints_section=hints,
        max_intents=max_intents,
    )


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""
