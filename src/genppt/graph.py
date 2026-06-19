"""LangGraph workflow for GenPPT — ReAct agent orchestration with quality iteration.

Includes checkpoint persistence: after each agent completes, the state is saved
to disk so that a failed run can resume from the last successful agent.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Literal

from langgraph.graph import StateGraph, START, END

from .state import GenPPTState, initial_state
from .agents import (
    content_director_node,
    content_design_node,
    ppt_design_node,
    chart_drawing_node,
    quality_review_node,
)

CHECKPOINT_DIR = Path(__file__).resolve().parent.parent.parent / ".genppt_checkpoints"

# Fields that are serializable and worth checkpointing
_CHECKPOINT_FIELDS = [
    "topic", "requirements", "variant_seed", "phase", "iteration_count",
    "max_iterations", "revision_count", "max_revisions", "revision_route",
    "creative_brief", "brief", "deck_plan", "slides", "design_concept",
    "design_specs", "agent_trace", "review_report", "needs_revision", "revision_focus", "error",
]


def _checkpoint_key(topic: str, requirements: str) -> str:
    """Deterministic checkpoint key from topic + requirements."""
    raw = f"{topic}|{requirements}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _checkpoint_path(topic: str, requirements: str) -> Path:
    return CHECKPOINT_DIR / f"{_checkpoint_key(topic, requirements)}.json"


def _save_checkpoint(state: GenPPTState) -> None:
    """Persist serializable state fields to a checkpoint file."""
    try:
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        cp_path = _checkpoint_path(state["topic"], state.get("requirements", ""))
        snapshot = {k: state.get(k) for k in _CHECKPOINT_FIELDS}
        cp_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # checkpoint save is best-effort, never block the pipeline


def _load_checkpoint(topic: str, requirements: str) -> dict | None:
    """Load a previous checkpoint if it exists and is valid."""
    cp_path = _checkpoint_path(topic, requirements)
    if not cp_path.exists():
        return None
    try:
        return json.loads(cp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _clear_checkpoint(topic: str, requirements: str) -> None:
    """Remove checkpoint after successful completion."""
    cp_path = _checkpoint_path(topic, requirements)
    try:
        cp_path.unlink(missing_ok=True)
    except OSError:
        pass


def _orchestrator_node(state: GenPPTState) -> GenPPTState:
    """Orchestrator: routes between agents based on current phase."""
    phase = state.get("phase", "init")
    verbose = state.get("verbose", False)

    if verbose and phase != "init":
        print(f"\n{'─'*50}")
        print(f"  🧭 Orchestrator: phase={phase} → ", end="")

    review_result = _evaluate_review(state) if phase == "review" and state.get("review_report") else None
    transitions = {
        "init": "director",
        "director": "content",
        "content": "content",
        "design": "design",
        "chart": "chart",
        "review": review_result or "review",
        "done": "done",
    }

    next_phase = transitions.get(phase, phase)
    state["phase"] = next_phase
    state["iteration_count"] = state.get("iteration_count", 0) + 1

    # ── Stream review / revision events ──
    stream = state.get("_stream_callback")
    if stream and phase == "review":
        report = state.get("review_report", {})
        stream.review(
            passed=report.get("passed", False),
            score=report.get("overall_score", 0),
            issues=len(report.get("issues", [])),
            summary=report.get("summary", ""),
        )
        if state.get("needs_revision") and next_phase not in ("done", "review"):
            stream.revision(
                count=state.get("revision_count", 0),
                max_count=state.get("max_revisions", 2),
                route=state.get("revision_route", ""),
                focus=state.get("revision_focus", []),
            )

    if verbose:
        print(f"→ {next_phase}")

    # Save checkpoint after each phase transition
    if next_phase not in ("init", "done"):
        _save_checkpoint(state)

    # Safety: force stop if iteration limit exceeded
    if state["iteration_count"] > state.get("max_iterations", 12):
        state["phase"] = "done"
        state["error"] = f"{state.get('error', '')}; 超过最大迭代次数({state['max_iterations']})".strip("; ")
        if stream:
            stream.error("orchestrator", f"超过最大迭代次数({state['max_iterations']})")
    return state


def _evaluate_review(state: GenPPTState) -> str:
    """After review, decide: done or back to revision based on primary route.

    When revision limit is exhausted but quality still fails, the human-in-the-loop
    flag is raised so the stream layer can pause for user intervention.
    """
    needs_revision = state.get("needs_revision", False)
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 2)

    if needs_revision and revision_count <= max_revisions:
        # Determine primary revision route from suggestions
        suggestions = state.get("review_report", {}).get("revision_suggestions", [])
        routes = set()
        for s in (suggestions or []):
            route = s.get("route", "ContentDesign")
            routes.add(route)
        # Route to earliest agent in pipeline: ContentDirector > ContentDesign > PPTDesign > ChartDrawing
        if "DesignConcept" in routes:
            state["revision_route"] = "director"
        elif "ContentDesign" in routes:
            state["revision_route"] = "content"
        elif "PPTDesign" in routes:
            state["revision_route"] = "design"
        elif "ChartDrawing" in routes:
            state["revision_route"] = "chart"
        else:
            state["revision_route"] = "content"
        return state["revision_route"]

    # Revision limit exhausted but quality still fails → human must decide
    if needs_revision:
        state["awaiting_human"] = True
        stream = state.get("_stream_callback")
        if stream:
            report = state.get("review_report", {})
            stream.awaiting_human(
                issues=report.get("issues", []),
                summary=f"自动修订{revision_count}轮后仍有{len(report.get('issues', []))}个问题，等待人工决策",
            )
    return "done"


def _route_after_orchestrator(state: GenPPTState) -> Literal[
    "content_director", "content_design", "ppt_design", "chart_drawing", "quality_review", "__end__"
]:
    """Route to the appropriate sub-agent or end."""
    phase = state.get("phase", "done")

    routing = {
        "director": "content_director",
        "content": "content_design",
        "design": "ppt_design",
        "chart": "chart_drawing",
        "review": "quality_review",
        "done": "__end__",
    }
    return routing.get(phase, "__end__")


def _after_agent_route(state: GenPPTState) -> Literal["orchestrator"]:
    """After any sub-agent, always return to orchestrator for evaluation."""
    return "orchestrator"


def _with_retry_and_stream(node_fn, node_name: str, max_retries: int = 2):
    """Wrap an agent node with retry on failure AND streaming event emission."""
    def wrapper(state: GenPPTState) -> GenPPTState:
        stream = state.get("_stream_callback")
        last_error = ""
        if stream:
            stream.agent_start(node_name, state.get("phase", "?"),
                               message=_agent_label(node_name, state))
        for attempt in range(max_retries + 1):
            try:
                result = node_fn(state)
                if stream:
                    _emit_agent_end(stream, node_name, result)
                return result
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    import time
                    time.sleep(1.5 * (attempt + 1))
        state["error"] = f"{state.get('error', '')}; {node_name} 重试{max_retries}次后仍失败: {last_error}".strip("; ")
        state["phase"] = "done"
        if stream:
            stream.error(node_name, last_error)
            stream.done()
        return state
    wrapper.__name__ = node_fn.__name__
    return wrapper


def _agent_label(node_name: str, state: GenPPTState) -> str:
    """Human-readable label for what an agent is about to do."""
    labels = {
        "content_director": f"正在分析「{state.get('topic', '')[:30]}」的需求与受众…",
        "content_design": f"正在撰写第{len(state.get('slides', [])) + 1}页文案…",
        "ppt_design": f"正在为{len(state.get('slides', []))}页幻灯片设计版式…",
        "chart_drawing": "正在分析哪些页面需要数据图表…",
        "quality_review": "正在进行12维度质量审查…",
    }
    return labels.get(node_name, f"正在执行 {node_name}…")


def _emit_agent_end(stream, node_name: str, state: GenPPTState) -> None:
    """Emit agent_end event with summary data from state."""
    trace = state.get("agent_trace", [])
    summary = trace[-1].get("summary", {}) if trace else {}
    messages = {
        "content_director": f"完成创作简报 — {summary.get('page_count', '?')}页, {summary.get('style_direction', '?')}风格",
        "content_design": f"完成{len(state.get('slides', []))}页文案撰写",
        "ppt_design": f"完成{len(state.get('design_specs', []))}页版式设计",
        "chart_drawing": f"完成{summary.get('selected_count', 0)}个数据图表",
        "quality_review": _review_end_message(state),
    }
    stream.agent_end(node_name, state.get("phase", ""), message=messages.get(node_name, ""), **summary)


def _review_end_message(state: GenPPTState) -> str:
    report = state.get("review_report", {})
    passed = report.get("passed", False)
    score = report.get("overall_score", "?")
    issues = len(report.get("issues", []))
    if passed:
        return f"审查通过 — {score}分"
    rev_count = state.get("revision_count", 0)
    max_rev = state.get("max_revisions", 2)
    route = state.get("revision_route", "")
    return f"审查发现{issues}个问题 — 第{rev_count}/{max_rev}次修订 → {route}"


def build_genppt_graph() -> StateGraph:
    """Build the GenPPT LangGraph workflow.

    Graph structure:
        START → orchestrator → [agent] → orchestrator → ... → END

    The orchestrator routes to the correct agent based on state.phase.
    After quality review, the orchestrator decides whether to finish or
    loop back to content for revision.
    """
    graph = StateGraph(GenPPTState)

    # ── Nodes ──
    graph.add_node("orchestrator", _orchestrator_node)
    graph.add_node("content_director", _with_retry_and_stream(content_director_node, "content_director"))
    graph.add_node("content_design", _with_retry_and_stream(content_design_node, "content_design"))
    graph.add_node("ppt_design", _with_retry_and_stream(ppt_design_node, "ppt_design"))
    graph.add_node("chart_drawing", _with_retry_and_stream(chart_drawing_node, "chart_drawing"))
    graph.add_node("quality_review", _with_retry_and_stream(quality_review_node, "quality_review"))

    # ── Edges ──
    # Entry → orchestrator
    graph.add_edge(START, "orchestrator")

    # Orchestrator → agent (conditional)
    graph.add_conditional_edges("orchestrator", _route_after_orchestrator, {
        "content_director": "content_director",
        "content_design": "content_design",
        "ppt_design": "ppt_design",
        "chart_drawing": "chart_drawing",
        "quality_review": "quality_review",
        "__end__": END,
    })

    # Agent → back to orchestrator
    graph.add_edge("content_director", "orchestrator")
    graph.add_edge("content_design", "orchestrator")
    graph.add_edge("ppt_design", "orchestrator")
    graph.add_edge("chart_drawing", "orchestrator")
    graph.add_edge("quality_review", "orchestrator")

    return graph.compile()


# ── Public API ──

def run_genppt_graph(
    topic: str,
    requirements: str = "",
    variant_seed: int = 0,
    max_iterations: int = 18,
    max_revisions: int = 2,
    verbose: bool = False,
    stream_callback: "StreamCallback | None" = None,
) -> dict:
    """Run the full GenPPT LangGraph workflow and return the final state.

    Supports checkpoint recovery: if a previous run failed mid-pipeline,
    the next invocation with the same topic+requirements resumes from
    the last successful agent.

    If *stream_callback* is provided, real-time progress events are emitted
    at each agent start/end, review, and revision.
    """
    graph = build_genppt_graph()

    # Try to resume from checkpoint
    cp = _load_checkpoint(topic, requirements)
    if cp and cp.get("phase") not in ("init", "done", ""):
        resumed_phase = cp["phase"]
        state = initial_state(
            topic=topic, requirements=requirements,
            variant_seed=cp.get("variant_seed", variant_seed),
            max_iterations=max_iterations, max_revisions=max_revisions,
        )
        # Restore serialized fields from checkpoint
        for k in _CHECKPOINT_FIELDS:
            if k in cp and k not in ("topic", "requirements", "max_iterations", "max_revisions"):
                state[k] = cp[k]
        # Resume from the saved phase (re-run the agent that was about to start)
        state["phase"] = resumed_phase
        state["error"] = f"{state.get('error', '')}; [从检查点恢复, 阶段={resumed_phase}]".strip("; ")
    else:
        state = initial_state(
            topic=topic, requirements=requirements,
            variant_seed=variant_seed,
            max_iterations=max_iterations, max_revisions=max_revisions,
        )
    state["verbose"] = verbose
    if stream_callback is not None:
        state["_stream_callback"] = stream_callback  # type: ignore[typeddict-unknown-key]

    try:
        final_state = graph.invoke(state)
    except Exception as e:
        final_state = {**state, "error": str(e)}
        # Save checkpoint on failure so next run can resume
        _save_checkpoint(final_state)
        if stream_callback:
            stream_callback.error("graph", str(e))
            stream_callback.done()
        return final_state

    # Clear checkpoint on success
    _clear_checkpoint(topic, requirements)
    if stream_callback:
        stream_callback.done()
    return final_state
