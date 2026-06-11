"""
AI 预分析 — 用户输入自然语言 → 提取 origin 和 goal。
"""

import json
import re
from pathlib import Path
from typing import Optional

from flocks.dag.models import PreAnalysisResult
from flocks.utils.log import Log

logger = Log.create(service=__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


class ProjectAnalyzer:
    """用户输入 → 起点/目标 自动分析器"""

    CONFIDENCE_THRESHOLD = 0.6

    def __init__(self, session_manager, config: dict):
        self._session_manager = session_manager
        self._config = config

    async def analyze(self, user_input: str) -> PreAnalysisResult:
        """分析用户输入，提取 origin 和 goal"""
        ac = self._config.get("pre_analysis", {})
        provider = ac.get("provider", "openai")
        model = ac.get("model", "gpt-4o-mini")
        temperature = ac.get("temperature", 0.1)

        # 创建轻量 Session，无工具，单次调用
        session = await self._session_manager.create(
            provider=provider,
            model=model,
            tools=[],
            temperature=temperature,
            system_prompt="你是一个任务分析助手。请严格按照 JSON 格式输出。",
        )

        prompt = _load_prompt("pre_analysis.md")
        response = await session.send_message(
            f"{prompt}\n\n## 用户输入\n\n{user_input}"
        )

        js = _extract_json_block(response)
        try:
            result = PreAnalysisResult.model_validate_json(js)
        except Exception as e:
            logger.warning("pre_analysis.parse_failed", {"error": str(e)})
            return PreAnalysisResult(
                analyzable=False,
                confidence=0.0,
                missing_info=["AI 响应解析失败"],
                clarification_questions=[str(e)],
            )

        await session.close()
        return result

    def is_confident(self, result: PreAnalysisResult) -> bool:
        return result.analyzable and result.confidence >= self.CONFIDENCE_THRESHOLD


def _load_prompt(name: str) -> str:
    """加载 Prompt 模板"""
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning("prompt.not_found", {"name": name})
    return ""


def _extract_json_block(text: str) -> str:
    """从 LLM 响应中提取 JSON 代码块"""
    # 策略 1: ```json ... ```
    match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    # 策略 2: ``` ... ```
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if blocks:
        return blocks[-1]
    # 策略 3: 裸 JSON
    match = re.search(r"\{[^{}]*\"analyzable\"[^{}]*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    raise ValueError("无法从响应中提取 JSON")
