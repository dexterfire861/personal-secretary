# Personal Secretary

A locally-run, agentic personal AI built from the ground up: a frozen open-source model
(via Ollama) + an engineered memory system + agent orchestration over MCP tools. The
point is to **build the system, not the model** — operate the LLM as a component and
own the memory, retrieval, agent loop, and tool wiring.

See **[SPEC.md](SPEC.md)** for the architecture and milestones, and
**[ARCHITECTURE.md](ARCHITECTURE.md)** for how the running system fits together.

## Stack
- **Model runtime:** Ollama (`llama3.1:8b` for chat/reflection, `llama3.2:3b` for cheap
  classification, `nomic-embed-text` for embeddings).
- **Memory:** SQLite (`db.py`) + Chroma vector store (`embeddings.py`); three-signal
  retrieval + session-start reflection (`memory.py`, `reflect.py`).
- **Agent:** one shared core (`agent_runtime.py`) — a ReAct loop over MCP tools with
  Ollama native tool-calling.
- **Surfaces:** FastAPI server + React/Vite UI (`server.py`, `frontend/`), a background
  task worker (`worker.py`), and a terminal playground (`constant-chat.py`).

## Setup
```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
# pull models
ollama pull llama3.1:8b && ollama pull llama3.2:3b && ollama pull nomic-embed-text
# build the UI (optional; server falls back to static/ if absent)
cd frontend && npm install && npm run build && cd ..
```

## Run
```bash
./run.sh            # starts the background worker + API server on :8000
```
Or the terminal playground:
```bash
venv/bin/python constant-chat.py
```
