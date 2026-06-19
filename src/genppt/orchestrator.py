"""GenPPT agent workflow — now powered by LangGraph ReAct agents.

The public API (run_agent_orchestrated_deck, result_to_deck_dict) remains
compatible. Under the hood, the LangGraph graph in graph.py handles
orchestration with quality-driven iteration loops.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .models import Brief, DeckPlan, SlideCopy, SlidePlan
from .style import DesignConcept
from .tools.validators import resolve_structure


def _serialize_rhythm(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value else ""


@dataclass(slots=True)
class AgentEvent:
    node: str
    label: str
    summary: str
    review_prompt: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DeckResult:
    brief: Brief
    deck_plan: DeckPlan
    slide_plans: list[SlidePlan]
    slide_copies: list[SlideCopy]
    theme_name: str
    design_concept: DesignConcept | None = None
    design_specs: list[dict[str, Any]] = field(default_factory=list)
    workflow_issues: list[dict[str, Any]] = field(default_factory=list)
    agent_trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class OrchestratedDeck:
    result: DeckResult
    events: list[AgentEvent]


def run_agent_orchestrated_deck(
    topic: str,
    requirements: str = "",
    llm: Any = None,
    variant_seed: int = 0,
    enable_charts: bool | None = None,
    verbose: bool = False,
    **_kwargs: Any,
) -> OrchestratedDeck:
    """Run the GenPPT ReAct agent workflow via LangGraph.

    Returns the same OrchestratedDeck type for backward compatibility.
    """
    from .graph import run_genppt_graph

    final_state = run_genppt_graph(
        topic=topic,
        requirements=requirements,
        variant_seed=variant_seed,
        verbose=verbose,
    )

    # Convert graph state back to legacy types
    brief_dict = final_state.get("brief", {})
    deck_plan_dict = final_state.get("deck_plan", {})
    slides = final_state.get("slides", [])
    design_concept_dict = final_state.get("design_concept", {})
    design_specs = final_state.get("design_specs", [])
    review_report = final_state.get("review_report", {})
    agent_trace = final_state.get("agent_trace", [])
    error = final_state.get("error", "")

    brief = Brief(
        topic=brief_dict.get("topic", topic),
        requirements=brief_dict.get("requirements", requirements),
        page_count=brief_dict.get("page_count", len(slides) or 8),
        tone=brief_dict.get("tone", ""),
        audience=brief_dict.get("audience", ""),
        purpose=brief_dict.get("purpose", ""),
    )

    deck_plan = DeckPlan(
        title=deck_plan_dict.get("title", topic),
        core_claim=deck_plan_dict.get("core_claim", ""),
        audience_belief_to_change=deck_plan_dict.get("belief_to_shift", ""),
        narrative_mode=deck_plan_dict.get("narrative_logic", ""),
        slide_intents=[str(s.get("narrative_function", s.get("intent", s.get("narrative_role", "context")))) for s in slides],
        slide_roles=[str(s.get("role", s.get("intent", ""))) for s in slides],
        style_keywords=deck_plan_dict.get("style_keywords", []),
    )

    slide_plans: list[SlidePlan] = []
    slide_copies: list[SlideCopy] = []
    for i, s in enumerate(slides):
        idx = int(s.get("index", i + 1))
        intent = str(s.get("narrative_function", s.get("intent", "context")))
        slide_plans.append(SlidePlan(
            index=idx,
            intent=intent,
            job=intent,
            key_message=str(s.get("headline", "")),
            narrative_role=str(s.get("role", s.get("intent", ""))),
        ))
        slide_copies.append(SlideCopy(
            index=idx,
            headline=str(s.get("headline", "")),
            kicker=str(s.get("kicker", "")),
            body=[str(b) for b in (s.get("body") or [])],
            speaker_note=str(s.get("speaker_note", "")),
            visual_hint=str(s.get("visual_hint", "")),
        ))

    concept = None
    if design_concept_dict:
        concept = DesignConcept(
            visual_metaphor=str(design_concept_dict.get("visual_metaphor", "")),
            style_direction=str(design_concept_dict.get("style_direction", "")),
            primary_hex=str(design_concept_dict.get("primary_hex", "#111827")),
            background_hex=str(design_concept_dict.get("background_hex", "#F8FAFC")),
            accent_hex=str(design_concept_dict.get("accent_hex", "#2563EB")),
            accent_secondary_hex=str(design_concept_dict.get("accent_secondary_hex", "#10B981")),
            semantic_colors=design_concept_dict.get("semantic_colors", {}),
            type_scale_ratio=float(design_concept_dict.get("type_scale_ratio", 1.333)),
            base_size_pt=int(design_concept_dict.get("base_size_pt", 13)),
            max_title_size_pt=int(design_concept_dict.get("max_title_size_pt", 42)),
            font_family=str(design_concept_dict.get("font_family", "Microsoft YaHei")),
            spacing_mood=str(design_concept_dict.get("spacing_mood", "normal")),
            margin_multiplier=float(design_concept_dict.get("margin_multiplier", 1.0)),
            shape_style=str(design_concept_dict.get("shape_style", "sharp")),
            decoration_level=str(design_concept_dict.get("decoration_level", "minimal")),
            dark_mode_pages=design_concept_dict.get("dark_mode_pages", []),
            asymmetrical=bool(design_concept_dict.get("asymmetrical", False)),
            page_rhythm_notes=_serialize_rhythm(design_concept_dict.get("page_rhythm_notes", "")),
            design_rationale=str(design_concept_dict.get("design_rationale", "")),
            emphasized_principles=design_concept_dict.get("emphasized_principles", []),
            font_weight_headline=str(design_concept_dict.get("font_weight_headline", "bold")),
            font_weight_body=str(design_concept_dict.get("font_weight_body", "normal")),
        )

    theme_name = concept.style_direction.replace(" ", "_") if concept else "auto"

    issues = review_report.get("issues", [])
    if error:
        issues.append({"category": "system", "slide_index": None, "severity": "error", "message": error})

    result = DeckResult(
        brief=brief,
        deck_plan=deck_plan,
        slide_plans=slide_plans,
        slide_copies=slide_copies,
        theme_name=theme_name,
        design_concept=concept,
        design_specs=design_specs,
        workflow_issues=issues,
        agent_trace=agent_trace,
    )

    events = [
        AgentEvent(node="langgraph", label="LangGraph工作流", summary=f"审查分数: {review_report.get('overall_score', 'N/A')}",
                   data={"review_report": review_report}),
    ]

    return OrchestratedDeck(result=result, events=events)


def result_to_deck_dict(result: DeckResult) -> dict[str, Any]:
    """Convert DeckResult to a serializable dict. Signature unchanged for compatibility."""
    designs = {int(item.get("index") or 0): item for item in result.design_specs}
    slides: list[dict[str, Any]] = []
    for plan, slide_copy in zip(result.slide_plans, result.slide_copies):
        design = designs.get(slide_copy.index, {})
        slide = {
            "index": slide_copy.index,
            "intent": plan.intent,
            "job": plan.job,
            "narrative_role": plan.narrative_role,
            "headline": slide_copy.headline,
            "kicker": slide_copy.kicker,
            "body": slide_copy.body,
            "speaker_note": slide_copy.speaker_note,
            "visual_hint": slide_copy.visual_hint,
            "layout": resolve_structure(design),
            "design": design.get("design", {}),
            "design_reason": design.get("reason", ""),
            "visual_treatment": design.get("visual_treatment", {}),
            "composition_intent": design.get("composition_intent", ""),
            "shape_language": design.get("shape_language", ""),
            "color_treatment": design.get("color_treatment", {}),
            "typography_treatment": design.get("typography_treatment", {}),
        }
        if design.get("chart_spec"):
            slide["chart_spec"] = design["chart_spec"]
        slides.append(slide)

    concept_dict: dict[str, Any] = {}
    if result.design_concept:
        dc = result.design_concept
        concept_dict = {
            "visual_metaphor": dc.visual_metaphor,
            "style_direction": dc.style_direction,
            "shape_style": dc.shape_style,
            "decoration_level": dc.decoration_level,
            "spacing_mood": dc.spacing_mood,
            "dark_mode_pages": dc.dark_mode_pages,
            "asymmetrical": dc.asymmetrical,
            "page_rhythm_notes": dc.page_rhythm_notes,
            "design_rationale": dc.design_rationale,
            "primary_hex": dc.primary_hex,
            "background_hex": dc.background_hex,
            "accent_hex": dc.accent_hex,
            "accent_secondary_hex": dc.accent_secondary_hex,
            "semantic_colors": dc.semantic_colors,
            "font_family": dc.font_family,
            "base_size_pt": dc.base_size_pt,
            "max_title_size_pt": dc.max_title_size_pt,
            "type_scale_ratio": dc.type_scale_ratio,
        }

    return {
        "source_workflow": {
            "mode": "langgraph_react",
            "issues": result.workflow_issues,
            "agent_trace": result.agent_trace,
        },
        "brief": {
            "topic": result.brief.topic,
            "requirements": result.brief.requirements,
            "page_count": result.brief.page_count,
            "tone": result.brief.tone,
            "audience": result.brief.audience,
            "purpose": result.brief.purpose,
        },
        "deck_plan": {
            "title": result.deck_plan.title,
            "core_claim": result.deck_plan.core_claim,
            "audience_belief_to_change": result.deck_plan.audience_belief_to_change,
            "narrative_mode": result.deck_plan.narrative_mode,
            "slide_intents": result.deck_plan.slide_intents,
            "slide_roles": result.deck_plan.slide_roles,
            "style_keywords": result.deck_plan.style_keywords,
        },
        "theme_name": result.theme_name,
        "design_concept": concept_dict,
        "slides": slides,
    }
