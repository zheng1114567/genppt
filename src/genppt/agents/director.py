"""Content Director ReAct agent — the strategic mastermind that runs FIRST.

Produces a comprehensive Creative Brief covering all 5 analysis dimensions:
1. Requirement Analysis (topic, audience, purpose, tone)
2. Material Analysis (what's provided, what's missing)
3. Structure Planning (narrative arc, per-page roles, argument tree)
4. Visual Concept Design (colors, typography, spatial metaphor)
5. Image & Chart Requirements (what visuals each page needs)

All subsequent agents receive this Creative Brief and execute within its constraints.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from ..state import GenPPTState
from ..llm import get_chat_model
from ..tools import validate_brief
from ..tools.json_utils import extract_json, extract_json_from_messages, extract_page_count
from ..prompts import get_prompt


_DIRECTOR_PROMPT = None  # cached after first load


def _load_director_prompt() -> str:
    global _DIRECTOR_PROMPT
    if _DIRECTOR_PROMPT is None:
        _DIRECTOR_PROMPT = get_prompt("director", fallback=SYSTEM_PROMPT_HARDCODED)
    return _DIRECTOR_PROMPT


SYSTEM_PROMPT_HARDCODED = """你是 PPT 内容总监 (Content Director)。你是整个生成管道的总指挥——所有战略决策由你做出，后续 Agent 根据你的创作简报执行具体任务。

## 你的5步分析流程

### 第1步：需求分析 (Requirement Analysis)

深入理解主题本质：
- 这个主题在什么行业？解决什么具体问题？
- 谁会看这份PPT？如果多层受众（高管+执行层）同时在场，标注主次：
  - 输出格式: "首要: [角色]([决策权],关心[核心关切]) | 次要: [角色]([执行权],关心[核心关切])"
- 这份PPT要推动什么判断或行动？用一句话说清楚。
- 确定语气：用 ≤15 字(不含标点)的中文短语。如需更复杂描述，拆为主基调+副基调（各≤15字）。
- 标注知识盲区（全系统统一三级置信度）：
  - 高(>80%): 确定知道的行业事实
  - 中(50-80%): 有线索但不完全确定的推断
  - 低(<50%): 纯推测，后续 Agent 需验证
- 建议页数：核心判断数 × 1.5 + 2(开场收束)，结果 ±20% 取整。复杂判断每个可额外 +1 页。最终 3-20 页。

### 第2步：素材分析 (Material Analysis)

- 列出用户提供的原始素材（数据、文档、品牌规范等）
- 列出缺失的——要完成这份PPT还需要什么数据和证据？
- 标注信息局限性：哪些判断需要在信息不足的情况下做出？

### 第3步：结构规划 (Structure Planning)

- 设计叙事弧线：颠覆常识 | 两难抉择 | 逐步收窄 | 时间推演 | 自定义。解释为什么选择这个弧线。
- 核心主张 (core_claim): 可争论的一句话核心论点
- 认知转变 (belief_to_shift): "听众原本以为X，听完后意识到Y"
- 逐页角色分配 (page_roles): 每页分配 narrative_function 和 key_idea。要求：
  - 第1页 role=cover（开场冲击），最后页 role=closing（行动号召收束）
  - 连续页面 narrative_function 不能重复超过2页
  - 每页的 key_idea 是一个判断句（不是主题描述）
- 论点树: 主论点→子论点→证据的推理层次关系
- 风格关键词: 3-5个用于指导视觉设计的关键词

### 第4步：视觉方案设计 (Visual Concept Design)

基于前3步的分析结果设计完整的视觉方案：
- visual_metaphor: 用什么视觉比喻来表达主题本质（如"工程蓝图""数据仪表盘""编辑杂志"）
- 配色系统: primary_hex(主文字色) / background_hex(背景色) / accent_hex(唯一强调色) / accent_secondary_hex(辅助强调色) / semantic_colors(正/负/警告/信息)
- 全篇统一背景色系——要么全浅色，要么全深色，不能混用
- 字体系统: font_family / type_scale_ratio / base_size_pt / max_title_size_pt / font_weight_headline / font_weight_body
  字号选择原则（由你根据受众和场景判断，以下是启发）：
  - 高管/演讲场景 → base 14-16pt, max_title 44-52pt（远处可读）
  - 技术/阅读场景 → base 12-14pt, max_title 36-44pt（屏幕阅读舒适）
  - 数据密集场景 → base 11-13pt, max_title 32-38pt（信息密度优先）
- 空间基调 spacing_mood: compact(数据密集) | normal(通用) | airy(演讲冲击，慎用以免留白过多)
- 形状哲学 shape_style: sharp(技术/数据/金融) | rounded(品牌/故事/人文) | mixed
- 装饰级别 decoration_level: minimal(留白为主) | moderate(适度装饰) | rich(丰富层次)
- page_rhythm_notes: 输出为JSON对象（不是字符串！），字段: sections(数组，每项含pages/role/visual) + transitions(节奏描述)
- design_rationale: 1-3句解释设计决策如何回链到主题和受众
- emphasized_principles: 从 [one_idea_per_slide, generous_whitespace, single_accent, visual_hierarchy, consistency, contrast, alignment, data_ink_ratio] 中选择2-4个

### 第5步：配图需求分析 (Image & Chart Requirements)

分析哪些页需要视觉素材支撑论点：
- charts: 哪页有可量化数据需要图表？建议类型(bar/line/pie/radar/funnel/scatter)和数据来源
- images: 哪页需要示意插图或照片？具体描述画面内容
- icons: 哪页需要图标标记？数量和风格（outline/solid）

## 工具

- `validate_brief(brief)`: 检查创作简报完整性和质量。最多调用 2 次——生成→检查→修正→再检查→输出。

## 输出格式

严格 JSON：
```json
{
  "topic": "原始主题",
  "requirements": "原始要求",
  "page_count": 8,
  "requirement_analysis": {
    "topic_essence": "一句话概括主题本质",
    "audience": "复合受众描述，标注主次",
    "purpose": "推动什么判断或行动",
    "tone": "≤15字不含标点",
    "sub_tone": null,
    "knowledge_confidence": {
      "known": ["确定事实1(高)"],
      "inferred": ["推断1(中)"],
      "uncertain": ["不确定项1(低)"]
    }
  },
  "material_analysis": {
    "provided": ["用户提供的素材1"],
    "missing": ["缺乏的数据/证据1"],
    "limitations": "信息局限性说明"
  },
  "structure_plan": {
    "narrative_arc": "颠覆常识|两难抉择|逐步收窄|时间推演|自定义",
    "narrative_arc_rationale": "为什么选择这个弧线",
    "core_claim": "可争论的核心主张",
    "belief_to_shift": "听众从X认知转变为Y",
    "narrative_logic": "页面间的因果/递进关系描述",
    "style_keywords": ["关键词1", "关键词2", "关键词3"],
    "page_roles": [
      {"index": 1, "role": "cover", "narrative_function": "开场冲击", "key_idea": "一个判断句"},
      {"index": 2, "role": "content", "narrative_function": "建立问题", "key_idea": "一个判断句"}
    ],
    "argument_tree": "主论点→子论点→证据的推理关系"
  },
  "visual_concept": {
    "visual_metaphor": "视觉比喻",
    "style_direction": "风格方向名称",
    "primary_hex": "#111827",
    "background_hex": "#F8FAFC",
    "accent_hex": "#2563EB",
    "accent_secondary_hex": "#10B981",
    "semantic_colors": {"positive": "#059669", "negative": "#DC2626", "warning": "#D97706", "info": "#2563EB"},
    "type_scale_ratio": 1.333,
    "base_size_pt": 14,
    "max_title_size_pt": 44,
    "font_family": "Microsoft YaHei",
    "font_weight_headline": "bold",
    "font_weight_body": "normal",
    "spacing_mood": "normal",
    "margin_multiplier": 1.0,
    "asymmetrical": false,
    "shape_style": "sharp",
    "decoration_level": "minimal",
    "dark_mode_pages": [],
    "emphasized_principles": ["one_idea_per_slide", "single_accent"],
    "page_rhythm_notes": {"sections": [{"pages": "1", "role": "封面冲击", "visual": "大标题+airy间距"}], "transitions": "节奏描述"},
    "design_rationale": "设计决策回链主题和受众的理由"
  },
  "image_chart_requirements": {
    "charts": [...],
    "images": [...],
    "icons": [...]
  },
  "content_boundary": {
    "max_title_chars": 18,
    "max_body_items_per_page": 4,
    "max_total_words": 600,
    "prefer_short_body": true
  }
}
```

## 核心原则

- audience 必须是具体的人。反面: "产品团队" → 正面: "首要:产品VP(决定是否投入8周) | 次要:2名Senior PM(评估流程适配)"
- tone ≤15字不含标点。反面: "专业" → 正面: "数据说话 不给模糊结论"
- page_roles 的 key_idea 必须每页不同且有判断力，不是主题描述
- page_rhythm_notes 必须输出为 JSON 对象，不是字符串
- 所有颜色用 #RRGGBB 十六进制格式
- knowledge_confidence.known 为空时在 uncertain 中标注 "[需人工补充]"

## 设计原则速查 (来自 design_principles.py)

以下是硬性设计约束，你的 visual_concept 输出必须遵守：
- **一页一个判断**: 每页一个核心主张，不混合多个主题
- **3秒可扫读**: 每页≤75词，标题≤15字，确保观众3秒内抓住要点
- **留白≥40%**: 内容页空白区域≥40%，封面≥60%。空白是设计元素，不是浪费
- **模块化字号**: 所有字号从 type_scale_ratio 推导，禁止随意字号
- **每页≤4种字号**: 整套≤6种，超过就是噪音
- **正文≥12pt**: 投影场景正文≥18pt，屏幕≥12pt。标题≥24pt
- **对比度AA目标**: 正文对比度≥4.5:1，目标7:1。中灰色(#6B7280)只在≥14pt时使用
- **60-30-10色彩**: 60%主色(背景)，30%辅色(文字+面板)，10%强调色(唯一焦点)
- **每页一个强调色**: 每页最多一个accent色时刻，多个accent=没有accent
- **图表标题=结论**: 图表标题写"Q3收入增长22%"而不是"Q3收入"
- **统一模式**: 演讲模式(≤15词/页)或文档模式(密集)，二选一，不混用

这些是启发和边界，不是锁死的模板。你根据主题和受众具体判断。
"""


def content_director_node(state: GenPPTState) -> GenPPTState:
    """Content Director agent — strategic analysis first, then sub-agents execute."""
    llm = get_chat_model(temperature=0.6)
    materials = state.get("materials", "")
    requirements = state.get("requirements", "")

    revision_note = ""
    if state.get("needs_revision") and state.get("review_report"):
        review = state["review_report"]
        rev_count = state.get("revision_count", 0)
        max_rev = state.get("max_revisions", 2)
        revision_note = (
            f"\n\n⚠️ 第{rev_count}次修订(最多{max_rev}次)。\n"
            f"上次审查反馈:\n{json.dumps(review.get('issues', []), ensure_ascii=False)[:800]}\n"
            f"修订范围: 幻灯片 {state.get('revision_focus', [])}\n"
            f"请针对性调整结构规划或视觉方案，其他部分保持不变。"
        )

    user_msg = (
        f"主题: {state['topic']}\n"
        f"要求: {requirements or '无特殊要求'}\n"
        f"素材: {materials or '无用户提供的素材'}\n"
        f"{revision_note}\n\n"
        f"请完成5步分析，输出完整的创作简报JSON。"
    )

    messages = [SystemMessage(content=_load_director_prompt()), HumanMessage(content=user_msg)]

    verbose = state.get("verbose", False)
    if verbose:
        print(f"\n{'='*60}")
        print(f"  🎯 Content Director 思考中...")
        print(f"  输入: {state['topic'][:60]}")
        print(f"  要求: {requirements[:80] or '无'}")
        print(f"{'='*60}")

    for iteration in range(3):
        response = llm.invoke(messages)
        messages.append(response)
        if verbose:
            tool_count = len(response.tool_calls) if hasattr(response, "tool_calls") and response.tool_calls else 0
            print(f"\n  📤 LLM原始输出 ({len(str(response.content))}字符, {tool_count}个工具调用):")
            print(f"  {'─'*60}")
            print(str(response.content))
            print(f"  {'─'*60}")

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                if tc["name"] == "validate_brief":
                    brief = extract_json_from_messages(messages)
                    result = json.dumps(validate_brief(brief), ensure_ascii=False) if brief else "无法提取Creative Brief"
                    messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        else:
            cb = extract_json_from_messages(messages)
            if cb and cb.get("topic"):
                state["creative_brief"] = cb
                state["brief"] = _extract_brief_from_creative_brief(cb)
                state["design_concept"] = _extract_design_concept_from_creative_brief(cb)
                _append_trace(state, "ContentDirector", {
                    "page_count": state["brief"].get("page_count"),
                    "audience": state["brief"].get("audience"),
                    "purpose": state["brief"].get("purpose"),
                    "narrative_arc": cb.get("structure_plan", {}).get("narrative_arc", ""),
                    "core_claim": cb.get("structure_plan", {}).get("core_claim", ""),
                    "visual_metaphor": state["design_concept"].get("visual_metaphor", ""),
                    "style_direction": state["design_concept"].get("style_direction", ""),
                })

                # Quality gate: validate design concept
                from ..tools.validators import check_design_quality
                dq_issues = check_design_quality(state["design_concept"])
                if dq_issues:
                    state["error"] = f"{state.get('error', '')}; 设计质量警告: {len(dq_issues)}项".strip("; ")
                    # Don't block — just warn and continue

                state["phase"] = "content"
                if verbose:
                    print(f"  ✅ Director完成: {cb.get('page_count', '?')}页, 风格={state['design_concept'].get('style_direction','?')}")
                break

    if not state.get("creative_brief"):
        cb = extract_json_from_messages(messages) or {}
        state["creative_brief"] = cb
        state["brief"] = _extract_brief_from_creative_brief(cb)
        state["design_concept"] = _extract_design_concept_from_creative_brief(cb)
        if not cb:
            state["error"] = f"{state.get('error', '')}; ContentDirector: 解析失败使用fallback".strip("; ")
            state["brief"] = state.get("brief") or {
                "topic": state["topic"], "requirements": requirements,
                "page_count": extract_page_count(requirements),
                "tone": "具体、果断、数据驱动", "sub_tone": None,
                "audience": "需进一步明确", "purpose": "推动明确判断",
                "knowledge_confidence": {"known": [], "inferred": [], "uncertain": ["[需人工补充] 自动分析失败"]},
            }
        _append_trace(state, "ContentDirector", {
            "fallback": not bool(cb),
            "page_count": state.get("brief", {}).get("page_count"),
            "error": state.get("error", ""),
        })
        state["phase"] = "content"
    return state


def _append_trace(state: GenPPTState, agent: str, summary: dict[str, Any]) -> None:
    trace = state.setdefault("agent_trace", [])
    trace.append({"agent": agent, "summary": summary})


def _serialize_rhythm(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value else ""


def _extract_brief_from_creative_brief(cb: dict) -> dict:
    """Extract backward-compat brief from creative_brief.requirement_analysis."""
    ra = cb.get("requirement_analysis", {})
    return {
        "topic": cb.get("topic", ""),
        "requirements": cb.get("requirements", ""),
        "page_count": cb.get("page_count", 8),
        "tone": ra.get("tone", ""),
        "sub_tone": ra.get("sub_tone"),
        "audience": ra.get("audience", ""),
        "purpose": ra.get("purpose", ""),
        "knowledge_confidence": ra.get("knowledge_confidence", {}),
    }


def _extract_design_concept_from_creative_brief(cb: dict) -> dict:
    """Extract backward-compat design_concept from creative_brief.visual_concept."""
    vc = cb.get("visual_concept", {})
    return {
        "visual_metaphor": str(vc.get("visual_metaphor", "")),
        "style_direction": str(vc.get("style_direction", "")),
        "primary_hex": str(vc.get("primary_hex", "#111827")),
        "background_hex": str(vc.get("background_hex", "#F8FAFC")),
        "accent_hex": str(vc.get("accent_hex", "#2563EB")),
        "accent_secondary_hex": str(vc.get("accent_secondary_hex", "#10B981")),
        "semantic_colors": vc.get("semantic_colors", {}),
        "type_scale_ratio": float(vc.get("type_scale_ratio", 1.333)),
        "base_size_pt": int(vc.get("base_size_pt", 13)),
        "max_title_size_pt": int(vc.get("max_title_size_pt", 42)),
        "font_family": str(vc.get("font_family", "Microsoft YaHei")),
        "font_weight_headline": str(vc.get("font_weight_headline", "bold")),
        "font_weight_body": str(vc.get("font_weight_body", "normal")),
        "spacing_mood": str(vc.get("spacing_mood", "normal")),
        "margin_multiplier": float(vc.get("margin_multiplier", 1.0)),
        "shape_style": str(vc.get("shape_style", "sharp")),
        "decoration_level": str(vc.get("decoration_level", "minimal")),
        "dark_mode_pages": vc.get("dark_mode_pages", []),
        "asymmetrical": bool(vc.get("asymmetrical", False)),
        "page_rhythm_notes": _serialize_rhythm(vc.get("page_rhythm_notes", "")),
        "design_rationale": str(vc.get("design_rationale", "")),
        "emphasized_principles": vc.get("emphasized_principles", []),
    }


def _extract_page_count(requirements: str) -> int:
    for token in re.split(r"[\s,，]+", str(requirements).lower()):
        digit = re.match(r"(\d+)(?:页|pages?|slides?|p)?", token)
        if digit:
            return max(3, min(20, int(digit.group(1))))
    return 8


def extract_json_from_messages(messages: list) -> dict[str, Any] | None:
    for msg in reversed(messages):
        content = str(msg.content) if hasattr(msg, "content") else str(msg)
        parsed = extract_json(content.strip())
        if parsed:
            return parsed
    return None


def extract_json(text: str) -> dict[str, Any] | None:
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
