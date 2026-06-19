"""GenPPT FastAPI server with SSE streaming, prompt management, and human-in-the-loop.

Start with:
    python -m uvicorn genppt.server:app --host 127.0.0.1 --port 8080 --reload
    # or: python -m genppt.server

Access:
    http://127.0.0.1:8080          — Web UI
    http://127.0.0.1:8080/health   — Health check
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="GenPPT API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── In-memory store for active tasks ──
_active_tasks: dict[str, dict[str, Any]] = {}
_task_lock = threading.Lock()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0", "features": ["streaming", "prompt_versioning", "human_in_the_loop"]}


# ── SSE stream generation ──

async def _sse_event_generator(topic: str, requirements: str, variant_seed: int = 0) -> Any:
    """Run the graph in a thread and forward stream events to SSE."""
    from .stream import StreamCallback
    from .graph import run_genppt_graph
    from .orchestrator import result_to_deck_dict, run_agent_orchestrated_deck

    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_stream_event(event: Any) -> None:
        """Push a StreamEvent into the async queue from the worker thread."""
        payload = {
            "event": event.event,
            "agent": event.agent,
            "phase": event.phase,
            "message": event.message,
            "data": event.data,
            "timestamp": event.timestamp,
        }
        # asyncio.Queue.put_nowait is thread-safe
        try:
            event_queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # drop if consumer is too slow (shouldn't happen for SSE)

    callback = StreamCallback(on_event=on_stream_event)

    def _run() -> None:
        try:
            # Use the high-level API for full PPTX compatibility
            deck = run_agent_orchestrated_deck(
                topic, requirements, variant_seed=variant_seed, verbose=False,
            )
            payload = result_to_deck_dict(deck.result)
            # Inject stream events: the graph callback emitted agent_start/agent_end;
            # we also need review and done. Those are handled inside graph.py now.
            final_data = {
                "title": payload.get("deck_plan", {}).get("title", ""),
                "slide_count": len(payload.get("slides", [])),
                "overall_score": payload.get("source_workflow", {}).get("review_report", {}).get("overall_score", "N/A"),
                "output_path": "",
            }
            try:
                event_queue.put_nowait({"event": "done", "agent": "", "phase": "",
                                        "message": "生成完成", "data": final_data, "timestamp": time.time()})
            except asyncio.QueueFull:
                pass
        except Exception as exc:
            try:
                event_queue.put_nowait({"event": "error", "agent": "system", "phase": "",
                                        "message": str(exc), "data": {}, "timestamp": time.time()})
            except asyncio.QueueFull:
                pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # Stream events as SSE
    heartbeat_interval = 15  # seconds
    last_event_time = time.time()

    while thread.is_alive() or not event_queue.empty():
        try:
            payload = await asyncio.wait_for(event_queue.get(), timeout=1.0)
            last_event_time = time.time()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            # Send heartbeat comment to keep connection alive
            if time.time() - last_event_time > heartbeat_interval:
                yield ": heartbeat\n\n"
                last_event_time = time.time()

    # Drain remaining events
    while not event_queue.empty():
        try:
            payload = event_queue.get_nowait()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except asyncio.QueueEmpty:
            break

    yield "event: close\ndata: {}\n\n"


@app.get("/api/generate/stream")
async def generate_stream(
    topic: str = Query(..., description="PPT 主题"),
    requirements: str = Query("", description="要求"),
    variant_seed: int = Query(0, description="变体种子"),
):
    """SSE endpoint: stream agent progress as server-sent events."""
    return StreamingResponse(
        _sse_event_generator(topic, requirements, variant_seed),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── REST endpoint (non-streaming fallback) ──

@app.post("/api/generate")
async def generate_sync(
    request: Request,
):
    """Synchronous generation endpoint. Returns full result as JSON."""
    body = await request.json()
    topic = body.get("topic", "")
    requirements = body.get("requirements", "")
    variant_seed = body.get("variant_seed", 0)

    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")

    from .orchestrator import run_agent_orchestrated_deck, result_to_deck_dict

    deck = run_agent_orchestrated_deck(topic, requirements, variant_seed=variant_seed)
    payload = result_to_deck_dict(deck.result)
    return payload


# ── Human-in-the-loop: decision endpoint ──

@app.post("/api/human/decide")
async def human_decide(request: Request):
    """Submit a human decision for a paused generation task.

    Body:
        { "action": "accept" | "reject" | "edit",
          "task_id": "...",
          "edits": [ {"slide_index": 1, "field": "headline", "value": "new text"} ]  # only for action=edit
        }
    """
    body = await request.json()
    action = body.get("action", "accept")
    task_id = body.get("task_id", "")
    edits = body.get("edits", [])

    with _task_lock:
        if task_id not in _active_tasks:
            raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
        task = _active_tasks[task_id]
        task["human_decision"] = action
        task["human_edits"] = edits
        task["human_decided_at"] = time.time()

    return {"status": "ok", "action": action, "task_id": task_id}


# ── Static file serving (Web UI) ──

if STATIC_DIR.exists():
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── CLI runner ──

def main() -> None:
    import uvicorn
    uvicorn.run("genppt.server:app", host="127.0.0.1", port=8080, reload=True)


if __name__ == "__main__":
    main()
