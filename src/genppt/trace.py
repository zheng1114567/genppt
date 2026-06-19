"""Agent trace export helpers.

The trace is an auditable execution record: inputs, constraints, decisions,
checks, and review outcomes. It intentionally does not expose hidden model
chain-of-thought.
"""

from __future__ import annotations

import json
from typing import Any


def build_agent_trace_payload(deck_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a complete, user-facing trace payload from the exported deck JSON."""
    workflow = deck_payload.get("source_workflow", {}) or {}
    brief = deck_payload.get("brief", {}) or {}
    deck_plan = deck_payload.get("deck_plan", {}) or {}
    design_concept = deck_payload.get("design_concept", {}) or {}
    slides = deck_payload.get("slides", []) or []
    issues = workflow.get("issues", []) or []
    agent_trace = workflow.get("agent_trace", []) or []

    return {
        "trace_type": "auditable_agent_process",
        "note": "This file records observable agent decisions, inputs, checks, and outputs. It does not expose hidden model chain-of-thought.",
        "workflow": {
            "mode": workflow.get("mode", ""),
            "issue_count": len(issues),
            "issues": issues,
        },
        "input": {
            "topic": brief.get("topic", ""),
            "requirements": brief.get("requirements", ""),
            "page_count": brief.get("page_count", ""),
            "audience": brief.get("audience", ""),
            "purpose": brief.get("purpose", ""),
            "tone": brief.get("tone", ""),
        },
        "deck_strategy": {
            "title": deck_plan.get("title", ""),
            "core_claim": deck_plan.get("core_claim", ""),
            "belief_to_change": deck_plan.get("audience_belief_to_change", ""),
            "narrative_mode": deck_plan.get("narrative_mode", ""),
            "slide_intents": deck_plan.get("slide_intents", []),
            "slide_roles": deck_plan.get("slide_roles", []),
            "style_keywords": deck_plan.get("style_keywords", []),
        },
        "design_strategy": design_concept,
        "agent_steps": agent_trace,
        "slide_decisions": [
            {
                "index": slide.get("index"),
                "headline": slide.get("headline", ""),
                "intent": slide.get("intent", ""),
                "layout": slide.get("layout", ""),
                "design_reason": slide.get("design_reason", ""),
                "body": slide.get("body", []),
                "visual_hint": slide.get("visual_hint", ""),
                "chart_spec": slide.get("chart_spec"),
            }
            for slide in slides
        ],
    }


def agent_trace_markdown(trace_payload: dict[str, Any]) -> str:
    """Render trace payload as readable Markdown."""
    lines: list[str] = [
        "# Agent Trace",
        "",
        "> 这是可审计的 Agent 执行记录：输入、约束、决策、检查结果和输出摘要。它不是隐藏推理链。",
        "",
        "## 输入与目标",
    ]
    input_info = trace_payload.get("input", {}) or {}
    for key, label in [
        ("topic", "主题"),
        ("requirements", "要求"),
        ("page_count", "页数"),
        ("audience", "受众"),
        ("purpose", "目的"),
        ("tone", "语气"),
    ]:
        lines.append(f"- {label}: {input_info.get(key, '')}")

    deck = trace_payload.get("deck_strategy", {}) or {}
    lines.extend([
        "",
        "## 内容策略",
        f"- 标题: {deck.get('title', '')}",
        f"- 核心主张: {deck.get('core_claim', '')}",
        f"- 认知转变: {deck.get('belief_to_change', '')}",
        f"- 叙事逻辑: {deck.get('narrative_mode', '')}",
        f"- 页面意图: {', '.join(str(x) for x in deck.get('slide_intents', []))}",
        f"- 页面角色: {', '.join(str(x) for x in deck.get('slide_roles', []))}",
        f"- 风格关键词: {', '.join(str(x) for x in deck.get('style_keywords', []))}",
        "",
        "## 视觉策略",
    ])

    design = trace_payload.get("design_strategy", {}) or {}
    for key, label in [
        ("visual_metaphor", "视觉隐喻"),
        ("style_direction", "风格方向"),
        ("shape_style", "形状语言"),
        ("decoration_level", "装饰级别"),
        ("spacing_mood", "空间基调"),
        ("design_rationale", "设计理由"),
        ("primary_hex", "主文字色"),
        ("background_hex", "背景色"),
        ("accent_hex", "强调色"),
        ("accent_secondary_hex", "辅助强调色"),
    ]:
        value = design.get(key, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        lines.append(f"- {label}: {value}")

    lines.extend(["", "## Agent 执行记录"])
    steps = trace_payload.get("agent_steps", []) or []
    if not steps:
        lines.append("- 无 agent_trace 记录。")
    for i, step in enumerate(steps, 1):
        agent = step.get("agent", f"Agent {i}")
        summary = step.get("summary", {}) or {}
        lines.extend(["", f"### {i}. {agent}"])
        if isinstance(summary, dict):
            for key, value in summary.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                lines.append(f"- {key}: {value}")
        else:
            lines.append(f"- summary: {summary}")

    lines.extend(["", "## 逐页决策"])
    for slide in trace_payload.get("slide_decisions", []) or []:
        lines.extend([
            "",
            f"### 第 {slide.get('index')} 页: {slide.get('headline', '')}",
            f"- 意图: {slide.get('intent', '')}",
            f"- 版式: {slide.get('layout', '')}",
            f"- 设计理由: {slide.get('design_reason', '')}",
            f"- 视觉提示: {slide.get('visual_hint', '')}",
        ])
        body = slide.get("body", []) or []
        if body:
            lines.append("- 正文:")
            for item in body:
                lines.append(f"  - {item}")
        if slide.get("chart_spec"):
            lines.append(f"- 图表: {json.dumps(slide.get('chart_spec'), ensure_ascii=False)}")

    workflow = trace_payload.get("workflow", {}) or {}
    lines.extend([
        "",
        "## 质量问题",
        f"- issue_count: {workflow.get('issue_count', 0)}",
    ])
    for issue in workflow.get("issues", []) or []:
        lines.append(
            f"- [{issue.get('severity', '')}] {issue.get('category', '')} "
            f"slide={issue.get('slide_index', '')}: {issue.get('message', '')}"
        )

    lines.append("")
    return "\n".join(lines)
