"""Tests for GenPPT ReAct agents."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from genppt.state import GenPPTState, initial_state
from genppt.agents.director import content_director_node
from genppt.agents.theme import theme_analysis_node
from genppt.agents.content import content_design_node
from genppt.agents.design import ppt_design_node
from genppt.agents.review import quality_review_node


def _mock_chat_model(responses: list[dict]):
    """Build a mock that returns structured AIMessages."""
    mock = MagicMock()
    remaining = list(responses)

    def _invoke(messages, **kwargs):
        data = remaining.pop(0) if remaining else {}
        return AIMessage(content=json.dumps(data, ensure_ascii=False), tool_calls=[])

    mock.invoke = _invoke
    return mock


def test_content_director_produces_creative_brief() -> None:
    mock_llm = _mock_chat_model([
        {
            "topic": "AI客服质检",
            "requirements": "5页",
            "page_count": 5,
            "requirement_analysis": {
                "topic_essence": "客服质检误判导致一线不信任",
                "audience": "客服负责人和质检主管",
                "purpose": "决定是否做质检样本试点",
                "tone": "严谨可执行",
                "sub_tone": None,
                "knowledge_confidence": {"known": [], "inferred": [], "uncertain": []},
            },
            "material_analysis": {"provided": [], "missing": ["误判率数据"], "limitations": "需用户提供"},
            "structure_plan": {
                "narrative_arc": "逐步收窄",
                "narrative_arc_rationale": "先建立风险，再收敛试点",
                "core_claim": "先从高风险样本开始比全量更稳",
                "belief_to_shift": "听众从全量覆盖转向先控误判",
                "narrative_logic": "建立风险→证明成本→收窄试点",
                "style_keywords": ["严谨", "可信", "可落地"],
                "page_roles": [
                    {"index": 1, "role": "cover", "narrative_function": "开场冲击", "key_idea": "质检误判正在削弱信任"},
                    {"index": 2, "role": "content", "narrative_function": "建立问题", "key_idea": "误判成本远高于漏检"},
                ],
                "argument_tree": "主论点→子论点→证据",
            },
            "visual_concept": {
                "visual_metaphor": "数据仪表盘",
                "style_direction": "minimal data-driven",
                "primary_hex": "#111827",
                "background_hex": "#F8FAFC",
                "accent_hex": "#2563EB",
                "accent_secondary_hex": "#10B981",
                "semantic_colors": {},
                "type_scale_ratio": 1.333,
                "base_size_pt": 13,
                "max_title_size_pt": 42,
                "font_family": "Microsoft YaHei",
                "font_weight_headline": "bold",
                "font_weight_body": "normal",
                "spacing_mood": "airy",
                "margin_multiplier": 1.0,
                "asymmetrical": False,
                "shape_style": "sharp",
                "decoration_level": "minimal",
                "dark_mode_pages": [],
                "emphasized_principles": ["one_idea_per_slide"],
                "page_rhythm_notes": {"sections": [], "transitions": "一致深色"},
                "design_rationale": "数据驱动",
            },
            "image_chart_requirements": {"charts": [], "images": [], "icons": []},
        }
    ])

    with patch("genppt.agents.director.get_chat_model", return_value=mock_llm):
        state = initial_state(topic="AI客服质检", requirements="5页")
        result = content_director_node(state)

    assert len(result["creative_brief"]) > 0
    assert result["brief"]["page_count"] == 5
    assert result["brief"]["tone"] == "严谨可执行"
    assert result["phase"] == "content"


def test_theme_analysis_keeps_user_page_count() -> None:
    mock_llm = _mock_chat_model([
        {
            "topic": "AI客服质检",
            "requirements": "5页，给客服负责人评审",
            "page_count": 5,
            "tone": "严谨、可执行",
            "audience": "客服负责人和质检主管，关心质检覆盖率和误判风险",
            "purpose": "决定是否先做一个质检样本试点",
        }
    ])

    with patch("genppt.agents.theme.get_chat_model", return_value=mock_llm):
        state = initial_state(topic="AI客服质检", requirements="5页，给客服负责人评审")
        result = theme_analysis_node(state)

    assert result["brief"]["page_count"] == 5
    assert result["brief"]["audience"] == "客服负责人和质检主管，关心质检覆盖率和误判风险"
    assert result["phase"] == "planning"


def test_content_design_generates_slides() -> None:
    mock_llm = _mock_chat_model([
        {
            "deck_plan": {
                "title": "AI客服质检",
                "core_claim": "先从高风险会话样本开始比全量质检更稳",
                "belief_to_shift": "听众原本以为全量覆盖更好，听完后意识到先控误判更重要",
                "narrative_logic": "先建立风险，再收敛试点",
                "style_keywords": ["严谨", "证据", "可落地"],
            },
            "slides": [
                {"index": 1, "intent": "建立质检风险", "headline": "先控误判，再谈全量覆盖",
                 "body": ["高风险会话集中贡献主要投诉。", "误判会直接影响一线信任。"],
                 "visual_hint": "证据块", "kicker": "", "speaker_note": ""},
                {"index": 2, "intent": "证明误判成本", "headline": "误判成本比覆盖率更先决定试点成败",
                 "body": ["抽样复核能暴露规则边界。", "试点阶段应保留人工兜底。"],
                 "visual_hint": "指标对比", "kicker": "", "speaker_note": ""},
                {"index": 3, "intent": "提出试点边界", "headline": "试点边界要小到能周度复盘",
                 "body": ["先选一个队列。", "用一周数据判断是否扩展。"],
                 "visual_hint": "流程", "kicker": "", "speaker_note": ""},
            ],
        }
    ])

    with patch("genppt.agents.content.get_chat_model", return_value=mock_llm):
        state = initial_state(topic="AI客服质检", requirements="5页")
        state["brief"] = {"topic": "AI客服质检", "page_count": 3, "audience": "客服负责人"}
        state["creative_brief"] = {
            "topic": "AI客服质检", "page_count": 3,
            "requirement_analysis": {"audience": "客服负责人", "tone": "严谨", "purpose": "决定试点"},
            "structure_plan": {"page_roles": [], "narrative_arc": "", "core_claim": "",
                              "belief_to_shift": "", "narrative_logic": "", "style_keywords": []},
            "visual_concept": {"visual_metaphor": "", "primary_hex": "", "background_hex": "", "accent_hex": ""},
            "image_chart_requirements": {"charts": [], "images": [], "icons": []},
        }
        result = content_design_node(state)

    assert len(result["slides"]) == 3
    assert result["slides"][0]["headline"] == "先控误判，再谈全量覆盖"
    assert result["phase"] == "design"


def test_ppt_design_maps_structure_to_design() -> None:
    mock_llm = _mock_chat_model([
        {
            "page_rhythm_plan": "cover dark → light argument → close dark",
            "designs": [
                {"index": 1, "structure": "hero_cover", "layout_strategy": "hero title centered",
                 "focal_element": "headline", "color_treatment": {"bg": "dark", "accent_placement": "top_strip"},
                 "spatial_strategy": "generous_whitespace", "shape_language": "minimal_lines_only",
                 "typography_treatment": "hero_size_headline",
                 "design": {"structure": "centered", "body_columns": 1, "title_size": 46, "body_size": 13, "spacing": "airy", "bg": "dark", "proportions": {"header": 0.26, "body": 0.2, "visual": 0}},
                 "reason": "开场页先建立判断"},
                {"index": 2, "structure": "title_split", "layout_strategy": "split left right",
                 "focal_element": "body_block", "color_treatment": {"bg": "light", "accent_placement": "left_bar"},
                 "spatial_strategy": "asymmetric_balance", "shape_language": "geometric_strict",
                 "typography_treatment": "mixed_weights",
                 "design": {"structure": "title_split", "body_columns": 1, "title_size": 28, "body_size": 13, "spacing": "normal", "bg": "light", "proportions": {"header": 0.16, "body": 0.38, "visual": 0.46}},
                 "reason": "证据页用左右分区"},
            ],
        }
    ])

    with patch("genppt.agents.design.get_chat_model", return_value=mock_llm):
        state = initial_state(topic="AI客服质检")
        state["slides"] = [
            {"index": 1, "intent": "cover", "headline": "先控误判", "body": ["开场"]},
            {"index": 2, "intent": "problem", "headline": "误判率上升", "body": ["数据", "证据"]},
        ]
        result = ppt_design_node(state)

    assert len(result["design_specs"]) == 2
    assert result["design_specs"][0]["design"]["structure"] == "centered"
    assert result["design_specs"][1]["design"]["structure"] == "title_split"
    assert result["phase"] == "chart"


def test_review_detects_issues() -> None:
    mock_llm = _mock_chat_model([
        {
            "passed": True,
            "overall_score": 8.5,
            "issues": [],
            "revision_focus": [],
            "revision_suggestions": {},
            "summary": "全部通过",
        }
    ])

    with patch("genppt.agents.review.get_chat_model", return_value=mock_llm):
        state = initial_state(topic="AI客服质检")
        state["brief"] = {"page_count": 3}
        state["slides"] = [
            {"index": 1, "role": "cover", "intent": "开场建立冲突", "headline": "质检误判正在削弱客服信任", "body": ["误判率14%(高,内部复核样本,n=300)。", "一线申诉量连续两周上升(高,客服工单)。"], "kicker": "", "speaker_note": ""},
            {"index": 2, "role": "content", "intent": "证明误判成本", "headline": "每1%误判带来3倍额外复核成本", "body": ["复核工时从每周12小时增至36小时(高,排班系统)。", "误判样本优先复核能让申诉关闭周期缩短2天(中,试点估算)。"], "kicker": "", "speaker_note": ""},
            {"index": 3, "role": "closing", "intent": "收束下一步", "headline": "先对一个高风险队列做两周试点", "body": ["下周选择投诉率最高的100通会话作为试点样本(高,质检池)。", "两周后按误判率低于5%决定是否扩展到全量(中,验收规则)。"], "kicker": "", "speaker_note": ""},
        ]
        state["design_specs"] = [
            {"index": 1, "design": {"structure": "centered", "bg": "dark"}, "color_treatment": {"bg": "dark"}},
            {"index": 2, "design": {"structure": "title_split", "bg": "light"}, "color_treatment": {"bg": "light"}},
            {"index": 3, "design": {"structure": "accent_panel", "bg": "dark"}, "color_treatment": {"bg": "dark"}},
        ]
        result = quality_review_node(state)

    assert result["review_report"]["passed"]
    assert result["review_report"]["overall_score"] == 8.5
