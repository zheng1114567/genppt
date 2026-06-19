"""Streaming adapter for GenPPT graph execution.

Wraps the LangGraph workflow with real-time event callbacks, yielding
SSE-compatible event dicts as each agent starts and finishes.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from typing import Any

from .state import GenPPTState

# ── Event types ──

class StreamEvent:
    """A single streaming event emitted during graph execution."""

    __slots__ = ("event", "agent", "phase", "message", "data", "timestamp")

    def __init__(
        self,
        event: str,               # "agent_start" | "agent_end" | "progress" | "review" | "error" | "done"
        agent: str = "",
        phase: str = "",
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        self.event = event
        self.agent = agent
        self.phase = phase
        self.message = message
        self.data = data or {}
        self.timestamp = time.time()

    def to_sse(self) -> str:
        """Render as SSE data line."""
        import json
        payload = {
            "event": self.event,
            "agent": self.agent,
            "phase": self.phase,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class StreamCallback:
    """Callback interface for graph execution streaming.

    Pass an instance to `run_genppt_graph(stream_callback=...)` to receive
    real-time events. For SSE, use `StreamCallback.as_sse_generator()`.
    """

    __slots__ = ("_queue", "_on_event")

    def __init__(self, on_event: Callable[[StreamEvent], None] | None = None) -> None:
        self._queue: list[StreamEvent] = []
        self._on_event = on_event

    def __call__(self, event: StreamEvent) -> None:
        self._queue.append(event)
        if self._on_event:
            self._on_event(event)

    @property
    def events(self) -> list[StreamEvent]:
        return list(self._queue)

    def agent_start(self, agent: str, phase: str, message: str = "", **data: Any) -> None:
        self(StreamEvent("agent_start", agent=agent, phase=phase, message=message, data=data))

    def agent_end(self, agent: str, phase: str, message: str = "", **data: Any) -> None:
        self(StreamEvent("agent_end", agent=agent, phase=phase, message=message, data=data))

    def progress(self, message: str, **data: Any) -> None:
        self(StreamEvent("progress", message=message, data=data))

    def review(self, passed: bool, score: float = 0, issues: int = 0, summary: str = "") -> None:
        self(StreamEvent("review", agent="QualityReview", message=summary, data={
            "passed": passed, "overall_score": score, "issue_count": issues,
        }))

    def revision(self, count: int, max_count: int, route: str, focus: list[int] | None = None) -> None:
        self(StreamEvent("progress", agent="orchestrator", message=f"第{count}/{max_count}次修订 → {route}", data={
            "revision_count": count, "max_revisions": max_count, "revision_route": route,
            "revision_focus": focus or [],
        }))

    def error(self, agent: str, message: str) -> None:
        self(StreamEvent("error", agent=agent, message=message))

    def done(self, result: dict[str, Any] | None = None) -> None:
        self(StreamEvent("done", message="生成完成", data=result or {}))

    def awaiting_human(self, issues: list[dict[str, Any]], summary: str = "") -> None:
        self(StreamEvent("progress", agent="orchestrator", phase="awaiting_human",
                         message="等待人工决策", data={
                             "state": "awaiting_human",
                             "issues": issues,
                             "summary": summary,
                         }))

    # ── Generator mode for SSE ──

    def as_sse_generator(self) -> Generator[str, None, None]:
        """Yield already-emitted events as SSE strings.

        Use this when you've collected all events and want to replay them.
        For true streaming, pass an `on_event` callback that writes to an asyncio.Queue.
        """
        for ev in self.events:
            yield ev.to_sse()

    def clear(self) -> None:
        self._queue.clear()
