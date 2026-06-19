from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SlideIntent = str

NarrativeMode = str

LayoutType = str


@dataclass(slots=True)
class Brief:
    topic: str
    requirements: str = ""
    audience: str = "general"
    purpose: str = "inform"
    page_count: int = 8
    tone: str = "professional, natural, concrete"
    must_include: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeckPlan:
    title: str
    core_claim: str
    audience_belief_to_change: str
    narrative_mode: NarrativeMode
    slide_intents: list[SlideIntent]
    style_keywords: list[str]
    slide_roles: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SlidePlan:
    index: int
    intent: SlideIntent
    job: str
    key_message: str
    narrative_role: str = ""
    decision_basis: str = ""
    layout_candidates: list[str] = field(default_factory=list)
    max_words: int = 90


@dataclass(slots=True)
class SlideCopy:
    index: int
    headline: str
    kicker: str = ""
    body: list[str] = field(default_factory=list)
    speaker_note: str = ""
    visual_hint: str = ""


@dataclass(slots=True)
class LayoutSpec:
    slide_index: int
    layout_type: LayoutType
    density: Literal["low", "medium", "high"] = "medium"
    emphasis: Literal["headline", "body", "visual", "balanced"] = "balanced"
    regions: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThemeSpec:
    name: str
    palette: list[str]
    font_family: str = "Microsoft YaHei"
    mood: str = "clean, calm, business"
    visual_rules: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QualityIssue:
    level: Literal["info", "warning", "error"]
    slide_index: int | None
    message: str
    suggestion: str = ""


@dataclass(slots=True)
class QualityReport:
    passed: bool
    issues: list[QualityIssue] = field(default_factory=list)
