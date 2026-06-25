# ARCHITECTURE — how the running system fits together

This is the map of the *running* system. For the vision and milestones see SPEC.md.

## Processes (two long-running + one scratch)
- **`server.py`** — FastAPI app. Interactive chat (agentic, streams events), session
  management, task API, status/reflections. Serves `frontend/dist` if built, else
  `static/`.
- **`worker.py`** — background task worker. Polls the `task_runs` queue, runs the agent
  on delegated prompts (read-only tools), logs `task_events`, supports cancellation.
- **`constant-chat.py`** — terminal playground over the same core. Not part of the
  served system; a scratch surface for testing.

Launch both with `./run.sh`.

## The one agent core — `agent_runtime.py`
`AgentRuntime` is shared by the server (chat) and the worker (tasks). It holds:
- `tool_schemas` — Ollama tool definitions (starts with `get_time`).
- `tool_registry` — `name -> callable`.
- `register_mcp_read_tools(client)` — bridges MCP tools (read allowlist) into the schemas
  + registry.
- `dispatch(tool_call)` — routes a tool call to its callable.
- `run(messages, emit, should_cancel)` — the ReAct loop: call Ollama with `tool_schemas`;
  if the model returns `tool_calls`, append the request, run each tool, append a
  `role:"tool"` result, loop; otherwise return the final answer. `emit` reports each
  step as an event; capped at `MAX_TOOL_ITERATIONS`.

## A chat turn (server)
1. `POST /api/chat` → `_build_chat_window`: `memory.retrieve(query)` embeds the query
   (`nomic-embed-text`), finds nearest memories in Chroma, scores them
   (`0.1·recency + 0.2·importance + 0.7·relevance`), and returns `[system + reflections]`
   + top memories; then session-recent messages are appended.
2. `AgentRuntime.run` executes in a **worker thread**; its `emit` pushes events onto a
   `queue.Queue`. The response is a **Server-Sent Events** stream that drains the queue:
   `session → model_step → tool_call → tool_result → final` (or `error`).
   (Thread→queue bridge mirrors `mcp_client.py`.)
3. On completion the user message and final answer are saved (`save_message` →
   SQLite + Chroma upsert + importance rating).
4. **Note:** the final answer arrives as one `final` event, not token-by-token
   (`run` calls Ollama non-streaming so it can inspect tool calls). Smooth final-token
   streaming is a future polish.

## A background task
`POST /api/tasks` enqueues a `task_runs` row → `worker.py` claims it
(`claim_next_task`, atomic) → runs `AgentRuntime.run` with read-only tools and a
cancellation check → streams `task_events` → marks completed/failed/cancelled.

## Memory — `db.py`, `embeddings.py`, `memory.py`, `reflect.py`
- **SQLite (`db.py`):** `messages`, `chat_sessions`, `reflections`, `task_runs`,
  `task_events`, `worker_heartbeats`.
- **Chroma (`embeddings.py`):** vector store over message content for semantic recall.
- **Retrieval (`memory.retrieve`):** three-signal score (recency, importance, relevance)
  with a cosine-distance cutoff.
- **Reflection (`reflect.py`):** at startup, extracts durable facts about the user and
  supersedes contradicted ones (soft-delete via `active=0`); injected into the system
  prompt.

## Model routing (`memory.py`)
- `BASE_MODEL` = `llama3.1:8b` — chat + reflection (quality).
- `FAST_MODEL` = `llama3.2:3b` — trivial classification (importance rating).
- `nomic-embed-text` — embeddings.
Swap models in one place. Multimodal (qwen2.5vl) is a *swap* route to add only when a
milestone consumes it.

## Tools — `mcp_client.py`
The MCP Python SDK is async; `MCPClient` is a **synchronous facade** that runs one
persistent MCP session in a background event-loop thread and exposes blocking
`list_tools()` / `call_tool()`. Today: the official **filesystem** server, **read-only**
tools (`read_text_file`, `list_directory`, `search_files`), scoped to a single root.

## Approval gate (deferred, not abandoned)
All exposed tools are read-only, so there is no approval gate wired yet. It re-enters —
in `AgentRuntime.dispatch` — the moment the first **write** tool is added (filesystem
write, gmail send). See SPEC.md §6.
