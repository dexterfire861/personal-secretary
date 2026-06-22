# SPEC.md — Personal Secretary

A locally-run, agentic personal AI built from the ground up. Frozen open-source
model + an engineered memory system + agent orchestration over MCP tools.
This file is the **source of truth** for what the system should do. Generated or
hand-written code is read back against this spec. **The spec is a ceiling, not a
floor:** anything not described here is guilty until proven necessary.

---

## 0. Owner & working agreement

- Builder: Aryaan. Background: AI/ML engineering (implemented DDPM, DPO, Word2Vec
  from scratch), builds MCP servers (Newsstand AI), infra experience (AWS, auth,
  load balancing). The math is not the gap; **systems integration** is the focus.
- Goal: build the *system*, not the model. Operate open-source models as
  components (like a database). Do NOT implement transformers, training loops, or
  serving layers — those are rented.
- Learning mode: **explain-then-I-write**. Aryaan writes the novel logic
  (retrieval scoring, reflection, agent glue) by hand to understand it. Boilerplate
  plumbing (file I/O, loop scaffolding, serialization) may be generated.
- See CLAUDE.md for collaboration rules.

## 1. Environment (locked)

- Machine: Apple Silicon Mac, **16GB RAM**, typically shared with Chrome, Cursor,
  Outlook, etc. Real free RAM is limited — model sizing must respect this.
- Runtime: **Ollama** (`localhost:11434`), Metal GPU backend.
- Current model: `llama3.1:8b` (4-bit, ~5GB). Watch for memory pressure when other
  apps are open; fall back to `llama3.2:3b` if it swaps. **The system must be
  model-agnostic** — model name is a single config value, swappable in one place.
- Language: Python. Dependency isolation via venv. Git from day one; `venv/` and
  any local memory store are gitignored.

## 2. Core mental model (the one idea everything rests on)

The model is **stateless**. Every `/api/chat` call is fresh; the only reason a
chatbot "remembers" is that prior messages are re-sent in the `messages` list.
This does not scale (context window fills, calls slow down, restarts = amnesia).

**A memory system is the answer to one question: when I cannot send everything,
what do I choose to send?** Everything below is machinery for computing the
"relevant slice" to inject into the `messages` list before each call.

The single foundational function is the chat call:
POST `/api/chat` with `{model, messages, stream:false}`, read
`response["message"]["content"]`. Memory is logic that runs *before* this call to
decide what goes in `messages`. Agents are logic that runs *after* it to act on
the response. Nothing replaces this function; everything wraps it.

## 3. Architecture — four layers

| Layer | Responsibility | Build vs. rent |
|---|---|---|
| **Model** | Local LLM via Ollama HTTP API; optional escalation to a hosted API for hard tasks | Rent the runtime; build the routing |
| **Memory** | Store every exchange externally; retrieve the relevant slice; reflect raw memories into insights | Build the logic; rent the vector DB |
| **Orchestration** | Agent loop (ReAct-style) over tools; background scheduler (reflection, briefings) | Build the glue; LangGraph optional for multi-step |
| **Tool / data** | MCP tools: Newsstand AI first, then filesystem, calendar, market data | Already Aryaan's strength — capabilities arrive as MCP tools, keeping modules swappable |

**Privacy default:** personal data (memory store, analytics) stays local. Hosted
APIs are opt-in per task and never receive the raw memory store.

## 4. Milestones (current state + roadmap)

### Milestone 0 — Local model talking — ✅ DONE
Python client hitting `/api/chat`, prints reply. Clean urllib-based client with
error handling already exists. (Note: `/api/create` and `/api/show` were explored
but are NOT part of the architecture — personality lives in runtime-injected
messages, never baked into a model file. Do not build on those endpoints.)

### Milestone 1 — Memory that persists — ✅ DONE
Persistence and a reload-on-restart chat loop exist. Storage went straight to
SQLite (`db.py`) rather than the interim JSON file — the recency-only retrieval
(`get_messages_for_context`) is still the fallback that seeds the context window.
Original spec below for reference.
Spec:
- A terminal chat loop: read `input()`, append user + assistant turns to a
  `messages` list, re-send each turn. (This deliberately hits the "stateless wall.")
- Persist conversation to disk so a restart reloads prior context (no amnesia).
- Retrieval v1 = **recency only**: load last-N exchanges from storage, inject them.
  No embeddings yet.
- **Open decision — storage format:** recommendation is start with a **JSON file**
  for Milestone 1 (simplest thing that works), migrate to **SQLite** at Milestone 2
  when reflection needs querying/filtering. Mark in code which is in use.
- Exit criterion: restart the script and it still "remembers" earlier conversation
  via reloaded last-N messages.

### Milestone 2 — Semantic memory + reflection — ✅ DONE
Built: Chroma vector store (`embeddings.py`) over `nomic-embed-text`; the
three-signal retrieval score `0.1·recency + 0.2·importance + 0.7·relevance` with
a `cos_distance > 0.5` cutoff (`memory.py:retrieve`); per-message importance
rating; and a session-start reflection job (`reflect.py`) that extracts durable
facts and injects them into the system prompt. Exit criterion met: reflection
surfaces facts about Aryaan across sessions.

**Interfaces.** Two entry points share the same memory/retrieval core:
- `constant-chat.py` — terminal REPL (the original spec target). Runs
  `run_reflection()` once at session start.
- `server.py` + `static/index.html` — a FastAPI server exposing `POST /chat`
  with token streaming, plus a static browser chat UI. This grew beyond the
  spec's "terminal chat loop"; it is now a supported surface, not stray scope.
  Both paths call `retrieve()` → `chat` → `save_message`, so memory behaves
  identically regardless of front-end.

**Deferred debt (not yet built — do not let it block M3, but track it):**
- Reflections only *append*; stale/contradicted facts are never superseded or
  removed at the storage layer (e.g. "interviewing" lingers after "accepted
  offer"). New reflections see old ones in-prompt but can't retract them.
- **Reflection cadence in the server is wrong:** `server.py` calls
  `run_reflection()` per `/chat` request, adding a blocking LLM round-trip to
  every turn and (given the no-supersede debt above) spamming near-duplicate
  reflections. Needs to move to a real cadence — server-startup, every-N-messages,
  or a timer. Open decision below.

Original spec below for reference.
- **Semantic retrieval:** embed each memory as a vector; embed the incoming
  message; retrieve nearest neighbors. Introduces an embedding model (local via
  Ollama, e.g. `nomic-embed-text`) and a vector DB (**Chroma** recommended — rent
  the store, build the retrieval logic on top).
- **Scoring (write this by hand — it's the heart):** combine **recency**,
  **importance**, and **relevance** into a retrieval score (Generative Agents
  pattern). This is novel logic, not boilerplate.
- **Reflection:** a scheduled background job reads raw memories and writes
  higher-level insights about Aryaan (e.g. "in active job search," "prefers blunt
  feedback"). First scheduled task. Likely the trigger to migrate to SQLite.
- Exit criterion: secretary surfaces something true about Aryaan it was never told
  directly in the current session, retrieved across sessions.

### Milestone 3 — Tools via MCP (agentic) — 🔨 CURRENT (not yet designed in detail)
- Secretary gains hands: calls MCP tools. **Newsstand AI first** (Aryaan built it),
  then filesystem, calendar.
- Introduces the ReAct reason-act loop and (optionally) LangGraph for orchestration.
- Human-approval gates for any tool that posts, sends, or spends.
- NOT designed in detail yet — do not pre-build Milestone 1/2 to anticipate this.

### Beyond — modules that ride on the spine (vision, not current work)
- **Content Intelligence:** ingest post analytics + transcripts, surface patterns,
  draft hooks in Aryaan's voice (veto retained).
- **Content Production pipeline:** Whisper transcription → rough-cut → caption drafts.
- **Finance Research agent:** background research over Newsstand AI + market data,
  thesis synthesis, **paper trading only** (strict risk rules — never real money
  until 3+ months logged paper trading and a defensible edge).
- **Voice fine-tune:** optional QLoRA on Aryaan's own writing (rented GPU, not local).

## 5. Design constraints / non-negotiables

- **16GB RAM is a forcing function**, not a bug: disciplined context management,
  cheap-by-default model routing, no waste. A bloated secretary is a failed one.
- **Model-agnostic:** never hardcode the model in multiple places.
- **Memory-first personality:** the secretary's "self" is retrieved context, never
  a baked model file. Anything that freezes personality outside the memory system
  is an anti-pattern.
- **Build the logic, rent the plumbing.** Do NOT reimplement vector DBs, schedulers,
  or serving. "From the ground up" = *architected and assembled by Aryaan*, not
  *infrastructure rewritten*.
- **Approval gates** on any action that posts, sends, spends, or deletes.

## 6. Open decisions (resolve as we reach them)
- [x] M1 storage: **SQLite** (`db.py`) — went straight to it, skipped the interim JSON file.
- [x] M2 vector DB: **Chroma** (`embeddings.py`, persistent client).
- [x] M2 embedding model: **`nomic-embed-text`** via Ollama `/api/embed`.
- [ ] Reflection supersede strategy: how do stale/contradicted reflections get
  retracted or replaced rather than just appended? (M2 deferred debt — resolve at M3.)
- [ ] Reflection cadence (server): currently per-request (wrong). Move to
  server-startup, every-N-messages, or a timer? (recommendation: every-N-messages.)
- [ ] M3 orchestration: hand-rolled ReAct loop vs. LangGraph (decide at M3).
- [ ] Model-routing: when does a task escalate from local to hosted API? (design at M3).
