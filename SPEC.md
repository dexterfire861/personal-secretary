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

**Deferred debt — RESOLVED:**
- ✅ Supersede: reflections are now stored one fact per row; a new fact carries a
  `replaces: <id>` tag and `reflect.py` flips the superseded fact to `active=0`
  (soft-delete, audit trail kept). "Interviewing" no longer lingers after "accepted
  offer."
- ✅ Reflection cadence: `run_reflection()` runs once at startup in both `server.py`
  and the REPL — the per-request blocking call is gone. Every-N-messages deferred
  (see open decisions).

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

### Milestone 3 — Tools via MCP (agentic) — 🔨 mostly shipped
**STATUS (2026-06):** One shared agent core (`agent_runtime.py`) used by the FastAPI
server (interactive chat) and the background worker. **Interactive chat now has hands** —
it runs the ReAct loop and streams structured events (`tool_call`/`tool_result`/`final`)
over SSE; verified firing `list_directory` against the real filesystem. Filesystem MCP
read tools (`read_text_file`, `list_directory`, `search_files`) registered at startup.
Model routing live (`FAST_MODEL` for importance rating). **Trimmed to essentials** —
approvals, connector dashboard, and multi-connector placeholders removed (chat + tasks +
memory only). Remaining (PARKED in favor of the M4 finance harness): filesystem **write +
approval gate**, then calendar/gmail. See ARCHITECTURE.md for the running data flow.

- Secretary gains hands: calls tools. First real MCP = **official filesystem server,
  read-only** (no auth, no gate — cheapest way to learn the MCP client). Then calendar
  / gmail (OAuth + write gates). **Building MCP servers is deliberately out of scope:**
  it's already Aryaan's strength — M3 is about the *client* + agent loop, not authoring
  servers. Newsstand AI is deprioritized (not running / not useful in its current
  state); integrate an existing server instead of forcing it.
- **Mechanism:** Ollama native tool-calling (`tools` param on `/api/chat`, model
  returns structured `message.tool_calls`). Hand-rolled ReAct *loop* (no LangGraph —
  it would hide the glue Aryaan is here to learn). The loop wraps the existing single
  `chat()` call: chat → if `tool_calls`, dispatch + append `role:"tool"` result →
  loop → else final answer.
- **Build-vs-rent:** the loop, `dispatch()`, and the approval gate are Aryaan's
  (novel glue). The MCP client (connect/list/call) and tool-schema bridge are rented
  plumbing (official MCP Python SDK).
- Human-approval gates for any tool that posts, sends, or spends — gate lives in
  `dispatch()`. Only bites on write tools, so it lands with the first write tool, not
  before.

**Slice plan (one working stopping point each):**
- **1a — loop against a trivial local tool — ✅ done.** REPL path
  (`constant-chat.py`), non-streaming. `TOOL_REGISTRY` + `TOOL_SCHEMAS` + `get_time`,
  `dispatch()`, and `run_agent()` (the loop, capped at `MAX_TOOL_ITERATIONS`). No MCP,
  no gate. `dispatch` verified in isolation; exit = live REPL run where `get_time`
  actually fires on "what time is it?".
- **1b — filesystem MCP read tools — ✅ done (live in chat + worker).** Server
  scoped to Aryaan's `aryaanverma` directory, **read+write, NO delete** (least
  privilege at the server boundary). But this slice **exposes only the read tools** to
  the model (`read_file`, `list_directory`) — the loop chooses which MCP tools to
  bridge into `TOOL_SCHEMAS`. Loop unchanged; add the MCP client (official Python SDK,
  stdio). The MCP-client learning step — no OAuth, no gate.
- **1b-write — expose filesystem write + build the approval gate.** Register the
  write tool; the gate lives in `dispatch()` and fires before any mutating call
  (overwrite is mutating even without delete). This is where the gate lands — with the
  first write tool, which is now filesystem, not gmail. One new thing at a time:
  client first (1b), gate second (1b-write).
- **1c — Google Calendar (read).** Reuse the MCP client; add Google OAuth. Read tools
  only (list events / freebusy) → no gate. First genuinely useful surface.
- **1d — Gmail (read→send).** Read first; send reuses the 1b-write gate. Then server
  (streaming) tool-calling. End of the M3 spine.

**Surfaces decided (2026-06): calendar, email, notes — Google ecosystem only.**
Considered and parked as *Beyond* (do NOT bolt MCPs on now): finance research /
prediction markets, content creation, personal finance. These are whole modules with
their own logic (risk rules, thesis synthesis, voice), not secretary reach-tools — a
tool with no module behind it does nothing. Tool-count discipline: an 8B model's
tool-selection degrades as the list grows, so keep registered tools to ~3–5.

Deferred out of M3 (over-build radar): model-routing/escalation (not needed to get
hands working), LangGraph, server-side streaming tool-calls.

### Milestone 4 — Prediction-market research harness (paper) — 🔨 ACTIVE DIRECTION
Promoted from "Beyond" (2026-06) — the one Beyond module brought forward; personal
finance and content stay parked. **Paper ONLY** — never real money until a defensible,
forward-tracked edge (Aryaan's own risk rule, non-negotiable).

**Arena: Kalshi** (CFTC-regulated, US-legal, clean API). Chosen over equities/filings
because it's *structurally less efficient* (fits "be better than enough people"), has
documented biases, and **resolves to clean YES/NO labels** → fast, honest out-of-sample
feedback. Caveat: low capacity (fine for research + a small pool, won't scale big).

**First hypothesis (the harness's acceptance test, not a commitment): news
under-reaction.** When news relevant to a market breaks at t₀, the implied probability
adjusts too slowly, leaving a window Δ (1h/6h/24h) to trade the news direction. Edge
exists only if price moves predictably *after* t₀. Crux = accurate news timestamps
aligned to markets (this is the make-or-break, not the agent).

**v1 = a forward-tracked prediction harness, scored end-to-end** (NOT a trading bot),
built on `agent_runtime` + the worker queue:
1. Kalshi ingest (free API): markets, intraday prices, resolution.
2. News timestamps: free first — **GDELT** or Aryaan's own **Newsstand AI**. (LSEG/
   Refinitiv deferred: enterprise-priced, entitlement-gated; only its Reuters *news*
   slice is relevant, and only worth it if v1 proves news quality is the binding
   constraint.)
3. Agent emits a structured call (market, direction, model prob vs market prob, rationale).
4. DB logs each call at t₀; scoring job grades on resolution (Brier/calibration + P&L
   vs price taken).
Done = one news-under-reaction call logged and scored against a real resolved market.
Build the harness logic by hand; rent the data/LLM. Codex's connector dashboard,
approvals, and multi-session stay dormant — do not extend or depend on them.

**Re-prioritization:** the M3 tool-layer work is now pointed at finance data (Kalshi +
news) in service of this harness. Generic calendar/gmail slices are PARKED; filesystem
read (1b) remains the MCP-client reference. Hosted-API escalation still deferred.

### Beyond — modules that ride on the spine (vision, not current work)
- **Personal finance:** read-only account/spend data + pattern surfacing. Parked.
- **Content Intelligence:** ingest post analytics + transcripts, surface patterns,
  draft hooks in Aryaan's voice (veto retained). Parked.
- **Content Production pipeline:** Whisper transcription → rough-cut → caption drafts.
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
- [x] Reflection supersede strategy: **LLM emits the mapping.** Active facts are
  fed into the reflection prompt with their ids; the LLM tags each new fact with the
  id it `replaces:` (or `none`). `reflect.py` parses per line, validates the id
  against the active set (hallucinated-id guard), calls `supersede_reflection(old_id)`,
  then inserts the new fact as its own row.
- [x] Reflection cadence (server): **startup-only** (matches the REPL). The
  per-request call is already gone. Every-N-messages deferred until a long-running
  server actually goes stale in practice.
- [x] M3 orchestration: **hand-rolled ReAct loop + Ollama native tool-calling.**
  No LangGraph (hides the glue). See Milestone 3 for the loop shape and slice plan.
- [x] M3 / slice 1b target: **official filesystem MCP server, read-only**, over the
  Python SDK's stdio transport. (Newsstand AI deprioritized — not running / not useful
  now. Authoring MCP servers is out of M3 scope; it's already Aryaan's strength.)
- [~] Model-routing: **local cheap-by-default routing started** — `FAST_MODEL`
  (`llama3.2:3b`) for trivial classification (importance rating); `BASE_MODEL` (8B)
  for chat + reflection. Minimal: two constants + a dispatch point, not an engine.
  Multimodal (qwen2.5vl for vision/video; Whisper for audio) is a *swap* route to add
  only when a milestone consumes it (content pipeline / finance chart-reading) — not
  speculatively (18GB RAM can't keep 8B + qwen warm). Hosted-API escalation still
  deferred — revisit if 8B tool-calling proves unreliable in the loop.
