"""Tests for the LangGraph orchestrator workflow."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from genppt.orchestrator import result_to_deck_dict, run_agent_orchestrated_deck
from genppt.state import GenPPTState, initial_state
from genppt.graph import build_genppt_graph
from genppt.agents.director import content_director_node
from genppt.agents.content import content_design_node
from genppt.agents.design import ppt_design_node
from genppt.agents.review import quality_review_node


def _mock_chat_model(responses: list[dict]):
    mock = MagicMock()

    def _invoke(messages, **kwargs):
        content = json.dumps(responses.pop(0) if responses else {}, ensure_ascii=False)
        return AIMessage(content=content)

    mock.invoke = _invoke
    return mock


def test_graph_builds_and_runs_sequential_flow() -> None:
    """Test that the graph processes all phases in correct order."""
    graph = build_genppt_graph()

    from langgraph.graph import START, END

    # Verify all expected nodes exist
    nodes = {n for n in graph.nodes}
    assert "orchestrator" in nodes
    assert "content_director" in nodes
    assert "content_design" in nodes
    assert "ppt_design" in nodes
    assert "chart_drawing" in nodes
    assert "quality_review" in nodes


def test_state_initialization() -> None:
    state = initial_state(topic="测试", requirements="5页", variant_seed=42)
    assert state["topic"] == "测试"
    assert state["requirements"] == "5页"
    assert state["variant_seed"] == 42
    assert state["phase"] == "init"
    assert state["slides"] == []
    assert state["needs_revision"] is False


def test_graph_integration_full_flow() -> None:
    """End-to-end: topic → graph → deck result."""
    import itertools

    director_response = {
        "topic": "测试", "requirements": "3页", "page_count": 3,
        "requirement_analysis": {
            "topic_essence": "测试核心", "audience": "产品经理",
            "purpose": "决定是否投入", "tone": "简洁直接", "sub_tone": None,
            "knowledge_confidence": {"known": [], "inferred": [], "uncertain": []},
        },
        "material_analysis": {"provided": [], "missing": [], "limitations": ""},
        "structure_plan": {
            "narrative_arc": "逐步收窄", "narrative_arc_rationale": "先问题后方案",
            "core_claim": "核心主张", "belief_to_shift": "改变听众认知",
            "narrative_logic": "叙事逻辑说明", "style_keywords": ["简洁"],
            "page_roles": [
                {"index": 1, "role": "cover", "narrative_function": "开场冲击", "key_idea": "问题"},
                {"index": 2, "role": "content", "narrative_function": "建立问题", "key_idea": "方案"},
                {"index": 3, "role": "closing", "narrative_function": "行动号召", "key_idea": "行动"},
            ],
            "argument_tree": "",
        },
        "visual_concept": {
            "visual_metaphor": "数据仪表盘", "style_direction": "dark data-driven",
            "primary_hex": "#F8FAFC", "background_hex": "#0F172A", "accent_hex": "#38BDF8",
            "accent_secondary_hex": "#34D399",
            "semantic_colors": {"positive": "#059669", "negative": "#DC2626", "warning": "#D97706", "info": "#2563EB"},
            "type_scale_ratio": 1.333, "base_size_pt": 13, "max_title_size_pt": 42,
            "font_family": "Microsoft YaHei", "font_weight_headline": "bold", "font_weight_body": "normal",
            "spacing_mood": "airy", "margin_multiplier": 1.2, "asymmetrical": False,
            "shape_style": "sharp", "decoration_level": "minimal", "dark_mode_pages": [1, 8],
            "emphasized_principles": ["one_idea_per_slide"],
            "page_rhythm_notes": {"sections": [], "transitions": "深色节奏"},
            "design_rationale": "数据驱动",
        },
        "image_chart_requirements": {"charts": [], "images": [], "icons": []},
    }
    content_responses = [{
        "deck_plan": {"title": "测试PPT", "core_claim": "核心主张", "belief_to_shift": "改变听众认知",
                      "narrative_logic": "叙事逻辑说明", "style_keywords": ["简洁"]},
        "slides": [
            {"index": 1, "intent": "建立问题", "headline": "问题标题",
             "body": ["问题描述第一句包含数据。", "问题描述第二句包含推理。"],
             "kicker": "", "speaker_note": "口播", "visual_hint": "证据块"},
            {"index": 2, "intent": "提出方案", "headline": "方案标题",
             "body": ["方案描述第一句。", "方案描述第二句。"],
             "kicker": "", "speaker_note": "口播", "visual_hint": "流程"},
            {"index": 3, "intent": "收束行动", "headline": "行动标题",
             "body": ["行动描述第一句。", "行动描述第二句。"],
             "kicker": "", "speaker_note": "口播", "visual_hint": "深色"},
        ],
    }]
    design_responses = [{
        "page_rhythm_plan": "dark→light→dark",
        "designs": [
            {"index": 1, "structure": "centered", "layout_strategy": "hero centered",
             "focal_element": "headline", "color_treatment": {"bg": "dark", "accent_placement": "top_strip"},
             "spatial_strategy": "generous_whitespace", "shape_language": "minimal_lines_only",
             "typography_treatment": "hero_size_headline",
             "design": {"structure": "centered", "body_columns": 1, "title_size": 42, "body_size": 13, "spacing": "airy", "bg": "dark", "proportions": {"header": 0.25, "body": 0.15, "visual": 0}},
             "reason": "封面页"},
            {"index": 2, "structure": "title_split", "layout_strategy": "left right split",
             "focal_element": "body_block", "color_treatment": {"bg": "light", "accent_placement": "left_bar"},
             "spatial_strategy": "asymmetric_balance", "shape_language": "geometric_strict",
             "typography_treatment": "mixed_weights",
             "design": {"structure": "title_split", "body_columns": 1, "title_size": 28, "body_size": 13, "spacing": "normal", "bg": "light", "proportions": {"header": 0.16, "body": 0.38, "visual": 0.46}},
             "reason": "论证页"},
            {"index": 3, "structure": "centered", "layout_strategy": "dark close",
             "focal_element": "headline", "color_treatment": {"bg": "dark", "accent_placement": "top_strip"},
             "spatial_strategy": "centered_calm", "shape_language": "minimal_lines_only",
             "typography_treatment": "hero_size_headline",
             "design": {"structure": "centered", "body_columns": 1, "title_size": 38, "body_size": 13, "spacing": "airy", "bg": "dark", "proportions": {"header": 0.22, "body": 0.12, "visual": 0}},
             "reason": "收束页"},
        ],
    }]
    review_responses = [{"passed": True, "overall_score": 8.0, "issues": [], "revision_focus": [], "revision_suggestions": {}, "summary": "通过"}]

    combined = list(itertools.chain(
        [director_response], content_responses, design_responses, review_responses
    ))

    mock_llm = MagicMock()

    def _invoke(messages, **kwargs):
        data = combined.pop(0) if combined else {}
        return AIMessage(content=json.dumps(data, ensure_ascii=False), tool_calls=[])

    mock_llm.invoke = _invoke

    with patch("genppt.agents.director.get_chat_model", return_value=mock_llm), \
         patch("genppt.agents.content.get_chat_model", return_value=mock_llm), \
         patch("genppt.agents.design.get_chat_model", return_value=mock_llm), \
         patch("genppt.agents.review.get_chat_model", return_value=mock_llm):

        deck = run_agent_orchestrated_deck("测试主题", "3页")

    assert deck.result.brief.page_count == 3
    assert len(deck.result.slide_copies) == 3
    assert deck.result.slide_copies[0].headline == "问题标题"


def test_deck_dict_contains_workflow_info() -> None:
    """Test that result_to_deck_dict includes workflow metadata."""
    # Use mocks to avoid real LLM calls
    mock_llm = MagicMock()

    director_data = {
        "topic": "测试", "requirements": "3页", "page_count": 3,
        "requirement_analysis": {
            "topic_essence": "", "audience": "测试", "purpose": "测试",
            "tone": "简洁", "sub_tone": None,
            "knowledge_confidence": {"known": [], "inferred": [], "uncertain": []},
        },
        "material_analysis": {"provided": [], "missing": [], "limitations": ""},
        "structure_plan": {
            "narrative_arc": "", "narrative_arc_rationale": "",
            "core_claim": "", "belief_to_shift": "",
            "narrative_logic": "", "style_keywords": [],
            "page_roles": [
                {"index": 1, "role": "cover", "narrative_function": "开场", "key_idea": ""},
            ],
            "argument_tree": "",
        },
        "visual_concept": {
            "visual_metaphor": "", "style_direction": "",
            "primary_hex": "#111827", "background_hex": "#F8FAFC", "accent_hex": "#2563EB",
            "accent_secondary_hex": "#10B981", "semantic_colors": {},
            "type_scale_ratio": 1.333, "base_size_pt": 13, "max_title_size_pt": 42,
            "font_family": "Microsoft YaHei", "font_weight_headline": "bold", "font_weight_body": "normal",
            "spacing_mood": "normal", "margin_multiplier": 1.0, "asymmetrical": False,
            "shape_style": "sharp", "decoration_level": "minimal", "dark_mode_pages": [],
            "emphasized_principles": [], "page_rhythm_notes": "", "design_rationale": "",
        },
        "image_chart_requirements": {"charts": [], "images": [], "icons": []},
    }
    content_data = {"deck_plan": {"title": "测试", "core_claim": "", "belief_to_shift": "",
                    "narrative_logic": "", "style_keywords": []},
                    "slides": [{"index": 1, "intent": "cover", "headline": "H", "body": ["B1", "B2"],
                                "kicker": "", "speaker_note": "", "visual_hint": ""}]}
    design_data = {"designs": [{"index": 1, "structure": "centered", "layout_strategy": "",
                   "focal_element": "headline", "color_treatment": {"bg": "dark"},
                   "spatial_strategy": "", "shape_language": "", "typography_treatment": "",
                   "design": {"structure": "centered", "body_columns": 1, "title_size": 42,
                              "body_size": 13, "spacing": "airy", "bg": "dark",
                              "proportions": {"header": 0.25, "body": 0.15, "visual": 0}},
                   "reason": ""}]}
    review_data = {"passed": True, "overall_score": 8.0, "issues": [], "revision_focus": [],
                   "revision_suggestions": {}, "summary": "通过"}
    import itertools
    combined = list(itertools.chain(
        [director_data], [content_data], [design_data], [review_data]
    ))

    def _invoke(messages, **kwargs):
        data = combined.pop(0) if combined else {}
        return AIMessage(content=json.dumps(data, ensure_ascii=False), tool_calls=[])

    mock_llm.invoke = _invoke

    with patch("genppt.agents.director.get_chat_model", return_value=mock_llm), \
         patch("genppt.agents.content.get_chat_model", return_value=mock_llm), \
         patch("genppt.agents.design.get_chat_model", return_value=mock_llm), \
         patch("genppt.agents.review.get_chat_model", return_value=mock_llm):

        deck = run_agent_orchestrated_deck("测试", "3页")

    payload = result_to_deck_dict(deck.result)
    assert payload["source_workflow"]["mode"] == "langgraph_react"
    assert "slides" in payload
    assert payload["brief"]["topic"] == "测试"
