import json
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent_runtime import AgentRuntime, get_filesystem_server_args
from mcp_client import MCPClient
from memory import BASE_MODEL, OLLAMA_HOST, N_EXCHANGES, save_message, retrieve
from db import (
    add_task_event,
    count_active_reflections,
    count_messages,
    count_sessions,
    create_task_run,
    create_session,
    get_active_reflections,
    get_messages_for_session_context,
    get_session,
    get_session_messages,
    get_task_run,
    list_sessions,
    list_task_events,
    list_task_runs,
    request_task_cancel,
    update_session_title,
)
from reflect import run_reflection

ROOT_DIR = Path(__file__).parent
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
STATIC_DIR = ROOT_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared agent core + filesystem MCP tools, mirroring worker.start_tools().
    # Degrade gracefully: if the MCP server can't start, chat still runs toolless.
    runtime = AgentRuntime()
    mcp = None
    try:
        mcp = MCPClient("npx", get_filesystem_server_args())
        mcp.start()
        registered = runtime.register_mcp_read_tools(mcp)
        print(f"[server] MCP read tools registered: {registered}")
    except Exception as error:  # noqa: BLE001 - startup must not hard-fail on MCP
        print(f"[server] MCP tools unavailable, chat runs without them: {error}")
    app.state.runtime = runtime
    app.state.mcp = mcp

    try:
        run_reflection()
    except Exception as error:  # noqa: BLE001
        print(f"[server] reflection skipped: {error}")

    yield

    if mcp is not None:
        mcp.stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionUpdateRequest(BaseModel):
    title: str


class TaskCreateRequest(BaseModel):
    prompt: str
    title: str | None = None


class TaskUpdateRequest(BaseModel):
    action: str = "cancel"


def _title_from_message(message: str) -> str:
    title = " ".join(message.strip().split())
    if not title:
        return "New chat"
    return title[:48].rstrip() + ("..." if len(title) > 48 else "")


def _dedupe_messages(messages: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for message in messages:
        key = (message.get("role"), message.get("content"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(message)
    return unique


def _build_chat_window(message: str, session_id: int) -> list[dict]:
    retrieved = retrieve(message, N_EXCHANGES)
    system_message = retrieved[0]
    memories = retrieved[1:]
    recent = get_messages_for_session_context(session_id, N_EXCHANGES)
    context = _dedupe_messages(memories + recent)
    return [system_message] + context + [{"role": "user", "content": message}]


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _agent_chat_response(req: ChatRequest):
    """Run the shared agent loop and stream its events (tool_call / tool_result /
    final / error) to the client as Server-Sent Events. The agent loop is sync and
    blocking, so it runs in a worker thread that feeds a queue the SSE generator
    drains — the same thread->queue bridge pattern used in mcp_client.py.
    """
    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")

    session = get_session(req.session_id) if req.session_id is not None else None
    if session is None:
        session = create_session(_title_from_message(text))
    session_id = session["id"]
    should_title = session["title"] == "New chat" and not get_session_messages(session_id)
    window = _build_chat_window(text, session_id)

    runtime: AgentRuntime = app.state.runtime
    events: "queue.Queue" = queue.Queue()
    sentinel = object()
    result_holder: dict = {}

    def emit(event_type: str, message: str, payload: dict | None = None):
        events.put({"type": event_type, "message": message, "payload": payload})

    def work():
        try:
            result_holder["result"] = runtime.run(window, emit=emit)
        except Exception as error:  # noqa: BLE001 - surface to the client, don't crash
            events.put({"type": "error", "message": str(error), "payload": None})
        finally:
            events.put(sentinel)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        yield _sse({"type": "session", "message": "session", "payload": {"session_id": session_id}})
        while True:
            event = events.get()
            if event is sentinel:
                break
            yield _sse(event)

        result = result_holder.get("result")
        if result:
            save_message("user", text, session_id=session_id)
            save_message("assistant", result, session_id=session_id)
            if should_title:
                update_session_title(session_id, _title_from_message(text))

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/sessions")
def sessions_endpoint():
    return {"sessions": list_sessions()}


@app.post("/api/sessions")
def create_session_endpoint(req: SessionCreateRequest):
    return create_session(req.title or "New chat")


@app.get("/api/sessions/{session_id}/messages")
def session_messages_endpoint(session_id: int):
    if get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"messages": get_session_messages(session_id)}


@app.patch("/api/sessions/{session_id}")
def update_session_endpoint(session_id: int, req: SessionUpdateRequest):
    title = " ".join(req.title.strip().split())
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    session = update_session_title(session_id, title[:80])
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/api/status")
def status_endpoint():
    runtime = getattr(app.state, "runtime", None)
    tools = sorted(runtime.tool_registry.keys()) if runtime else []
    return {
        "model": BASE_MODEL,
        "ollama_host": OLLAMA_HOST,
        "messages": count_messages(),
        "sessions": count_sessions(),
        "active_reflections": count_active_reflections(),
        "tools": tools,
        "capabilities": {
            "streaming_chat": True,
            "semantic_memory": True,
            "reflection": True,
            "tool_calling": True,
        },
    }


@app.get("/api/reflections")
def reflections_endpoint():
    return {"reflections": get_active_reflections()}


@app.get("/api/tasks")
def tasks_endpoint():
    return {"tasks": list_task_runs()}


@app.post("/api/tasks")
def create_task_endpoint(req: TaskCreateRequest):
    prompt = " ".join(req.prompt.strip().split())
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    title = req.title or _title_from_message(prompt)
    task = create_task_run(prompt, title=title)
    add_task_event(task["id"], "queued", "Task queued for the background worker.")
    return task


@app.get("/api/tasks/{task_id}/events")
def task_events_endpoint(task_id: int):
    if get_task_run(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"events": list_task_events(task_id)}


@app.get("/api/tasks/{task_id}")
def task_endpoint(task_id: int):
    task = get_task_run(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@app.patch("/api/tasks/{task_id}")
def update_task_endpoint(task_id: int, req: TaskUpdateRequest):
    if req.action != "cancel":
        raise HTTPException(status_code=400, detail="only cancel is supported")
    task = request_task_cancel(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    add_task_event(task_id, "cancel_requested", "Cancellation requested from the UI.")
    return task


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    return _agent_chat_response(req)


@app.post("/api/chat")
def api_chat_endpoint(req: ChatRequest):
    return _agent_chat_response(req)


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_react_app(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        requested = FRONTEND_DIST / full_path
        if full_path and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
