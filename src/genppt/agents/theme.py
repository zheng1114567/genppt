"""ThemeAnalysis ReAct agent — deeply analyzes topic and audience to produce a Brief."""

from __future__ import annotations

import json, re
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from ..state import GenPPTState
from ..llm import get_chat_model
from ..tools import validate_brief


SYSTEM_PROMPT = """你是 PPT 主题分析专家。你不是套模板，而是深入理解一个主题的本质、受众和目的。
你在管道最上游——你的分析决定后续所有 Agent 的工作方向。

## 工作流程

1. **理解主题**：这个主题在什么行业？解决什么具体问题？谁关心结果？
2. **分析受众**：谁会看这份PPT？（详见"复合受众"节）
3. **明确目的**：这份PPT要推动什么判断或行动？用一句话说清楚。
4. **确定语气**：用 ≤15 字(不含标点)的中文短语。如需更复杂描述，拆为主基调+副基调（各≤15字）。
5. **标注知识盲区**：用统一三级置信度标注你的理解程度（详见"知识盲区"节）
6. **调用 validate_brief**：基于前5步产出的 brief 调用工具检查，最多2次调用
7. **建议页数**：核心判断数 × 1.5 + 2(开场收束)，结果 ±20% 取整。复杂判断(需多页展开的对比/多方案)每个可额外 +1 页。最终 3-20 页。建议页数在 validate_brief 通过后确定。

步骤1-5产出的中间产物统称为"brief"，作为 validate_brief 的输入。

## 复合受众

如果多层受众(高管+执行层)同时在场，标注主次：
- 首要受众(设计倾斜): 谁的决策最关键？PPT 的叙事视角优先服务此人。
- 次要受众(兼顾): 谁在现场但优先级较低？
- 输出格式: "首要: [角色]([决策权],关心[核心关切]) | 次要: [角色]([执行权],关心[核心关切])"
- 例: "首要: 产品VP(投决权,关心ROI风险) | 次要: 工程Lead(执行权,关心可行性和工期)"

## 知识盲区

使用全系统统一三级置信度标注：
- 高(>80%): 确定知道的行业事实
- 中(50-80%): 有线索但不完全确定的推断
- 低(<50%): 纯推测，后续 Agent 需注意和验证
例: "已知: B2B SaaS产品,面向50-200人企业(高) | 推测: 竞品可能是X(中) | 不确定: 用户真实痛点优先级(低)"

## 工具

- `validate_brief(brief)`: 检查 Brief 完整性和质量。调用时机：完成步骤1-5后，输出前。
  最多调用 2 次——生成→检查→修正→再检查→输出。
  2次后仍不通过 → 在 knowledge_confidence.uncertain 中标注未解决的校验项，格式: "[validate_brief] 未解决: 问题描述"

## 输出格式

严格 JSON：
```json
{
  "topic": "原始主题",
  "requirements": "原始要求",
  "page_count": 8,
  "tone": "≤15字的中文短语（不含标点）",
  "sub_tone": "副基调 ≤15字,无副基调时填 null",
  "audience": "分层描述真实听众。多人时标注主次",
  "purpose": "一句话推动什么判断或行动",
  "knowledge_confidence": {
    "known": ["确定事实1(高)", "确定事实2(高)"],
    "inferred": ["有线索推断1(中)", "有线索推断2(中)"],
    "uncertain": ["不确定项1(低)", "不确定项2(低)"]
  }
}
```

## 核心原则

- audience 必须是具体的人。反面: "产品团队"(太笼统) → 正面: "首要:产品VP(决定是否投入8周) | 次要:2名Senior PM(评估流程适配)"
- tone ≤15字不含标点，sub_tone 同样约束。反面: "专业"(废话) → 正面: "数据说话 不给模糊结论"
- purpose 必须包含可验证的判断
- knowledge_confidence.known 为空是严重问题——说明你对主题完全不了解。此时仍须输出 JSON，但在 uncertain 中注明 "【需人工补充】主题信息不足，以下分析基于推测"
"""


def theme_analysis_node(state: GenPPTState) -> GenPPTState:
    llm = get_chat_model(temperature=0.5)
    user_msg = f"主题: {state['topic']}\n要求: {state['requirements'] or '无特殊要求'}\n\n请深入分析。如有知识盲区请标注置信度。"
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_msg)]

    for _ in range(3):
        response = llm.invoke(messages)
        messages.append(response)
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                if tc["name"] == "validate_brief":
                    brief = _extract_json_from_messages(messages)
                    result = json.dumps(validate_brief(brief), ensure_ascii=False) if brief else "无法提取Brief"
                    messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        else:
            brief = _extract_json_from_messages(messages)
            if brief and brief.get("topic"):
                state["brief"] = brief
                state["phase"] = "planning"
                break

    if not state.get("brief"):
        state["brief"] = _extract_json_from_messages(messages) or {
            "topic": state["topic"], "requirements": state["requirements"] or "",
            "page_count": _extract_page_count(state["requirements"]),
            "tone": "具体、果断、数据驱动", "sub_tone": None,
            "audience": "需进一步明确", "purpose": "推动明确判断",
            "knowledge_confidence": {"known": [], "inferred": [], "uncertain": ["【需人工补充】自动分析失败"]},
        }
        state["phase"] = "planning"
        state["error"] = f"{state.get('error', '')}; ThemeAnalysis: 解析失败使用fallback".strip("; ")
    return state


def _extract_page_count(requirements: str) -> int:
    for token in re.split(r"[\s,，]+", requirements.lower()):
        digit = re.match(r"(\d+)(?:页|pages?|slides?|p)?", token)
        if digit:
            return max(3, min(20, int(digit.group(1))))
    return 8


def _extract_json_from_messages(messages: list) -> dict[str, Any] | None:
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = _extract_json(content.strip())
        if parsed:
            return parsed
    return None


def _extract_json(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False; continue
        if ch == "\\":
            escape = True; continue
        if ch == '"' and not escape:
            in_string = not in_string; continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
    return None
