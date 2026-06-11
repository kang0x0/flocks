"""
Agent 输出校验 — 从 LLM 响应中提取并验证 JSON。
"""

import re
import json
from typing import Tuple

from flocks.dag.models import ReasonOutput, ExploreOutput
from flocks.utils.log import Log

logger = Log.create(service=__name__)


class OutputParseError(ValueError):
    """JSON 提取失败"""
    pass


def extract_json_block(text: str) -> str:
    """从 LLM 自由文本中提取 JSON 代码块

    支持:
    - ```json ... ```
    - ``` ... ```
    - 裸 JSON
    """
    # 策略 1: ```json ... ```
    match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if match:
        return match.group(1)

    # 策略 2: 最后一个 ```...``` 块
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if blocks:
        return blocks[-1]

    # 策略 3: 找文本末尾的 { ... }
    matches = list(re.finditer(r"\{[^{}]*\}(?:\s*\{[^{}]*\})*", text, re.DOTALL))
    if matches:
        # 尝试解析每个候选，返回最后一个有效的
        for m in reversed(matches):
            try:
                json.loads(m.group(0))
                return m.group(0)
            except json.JSONDecodeError:
                continue

    raise OutputParseError("无法从响应中提取 JSON")


def validate_reason_output(text: str) -> Tuple[ReasonOutput, bool]:
    """校验 Reason Agent 输出"""
    try:
        json_str = extract_json_block(text)
        output = ReasonOutput.model_validate_json(json_str)
        return output, True
    except Exception as e:
        logger.warning("reason.output.invalid", {"error": str(e)})
        return ReasonOutput(complete=False, reasoning=f"解析失败: {str(e)}"), False


def validate_explore_output(text: str) -> Tuple[ExploreOutput, bool]:
    """校验 Explore Agent 输出"""
    try:
        json_str = extract_json_block(text)
        output = ExploreOutput.model_validate_json(json_str)
        # 基本合法性检查
        if not output.new_fact.get("content"):
            return output, False
        return output, True
    except Exception as e:
        logger.warning("explore.output.invalid", {"error": str(e)})
        return ExploreOutput(
            new_fact={"id": "error", "content": f"解析失败: {str(e)}", "confidence": 0}
        ), False
