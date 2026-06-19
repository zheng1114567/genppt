"""GenPPT unified state definition for LangGraph ReAct workflow."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class GenPPTState(TypedDict):
    # ── Input ──
    topic: str
    requirements: str
    materials: str
    variant_seed: int
    verbose: bool

    # ── ReAct message history ──
    messages: Annotated[list[BaseMessage], add_messages]

    # ── Phase control ──
    phase: str  # init | director | content | design | chart | review | done
    iteration_count: int
    max_iterations: int
    revision_count: int
    max_revisions: int
    revision_route: str  # concept | content | design | chart — where to route on revision

    # ── Artifacts ──
    creative_brief: dict[str, Any]
    brief: dict[str, Any]
    deck_plan: dict[str, Any]
    slides: list[dict[str, Any]]
    design_concept: dict[str, Any]
    design_specs: list[dict[str, Any]]
    agent_trace: list[dict[str, Any]]

    # ── Quality ──
    review_report: dict[str, Any]
    needs_revision: bool
    revision_focus: list[int]  # slide indices to revise

    # ── Human-in-the-loop ──
    awaiting_human: bool  # True when revisions exhausted and human must decide
    human_decision: str   # "accept" | "reject" | "edit" — set by external API
    human_edits: list[dict[str, Any]]  # edits from human for action="edit"

    # ── Output ──
    deck: dict[str, Any]
    error: str


def initial_state(
    topic: str,
    requirements: str = "",
    variant_seed: int = 0,
    max_iterations: int = 3,
    max_revisions: int = 2,
) -> GenPPTState:
    return {
        "topic": topic,
        "requirements": requirements,
        "materials": "",
        "variant_seed": variant_seed,
        "verbose": False,
        "messages": [],
        "phase": "init",
        "iteration_count": 0,
        "max_iterations": max_iterations,
        "revision_count": 0,
        "max_revisions": max_revisions,
        "revision_route": "",
        "creative_brief": {},
        "brief": {},
        "deck_plan": {},
        "slides": [],
        "design_concept": {},
        "design_specs": [],
        "agent_trace": [],
        "review_report": {},
        "needs_revision": False,
        "revision_focus": [],
        "awaiting_human": False,
        "human_decision": "",
        "human_edits": [],
        "deck": {},
        "error": "",
    }
