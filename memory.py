import json
import math
import time
from pathlib import Path
from urllib.request import Request, urlopen

from db import (
    init_db, insert_message, update_importance,
    get_messages_for_context, get_messages_by_ids,
    get_reflections,
)
from embeddings import upsert, query_similar

# Storage: SQLite (M2) + Chroma vector store
BASE_MODEL = "llama3.1:8b"
EMBED_MODEL = "nomic-embed-text"
OLLAMA_HOST = "http://localhost:11434"
SYSTEM_PROMPT = (
    "You are Aryaan's personal secretary. You speak with him directly and "
    "conversationally — like a sharp, trusted chief of staff, not a chatbot. "
    "Never use memo format, headers, bullet lists, or filler like 'Next task?' "
    "or 'How can I help?' unless he explicitly asks for a list. Match his "
    "register: if he's casual or off-topic, be casual; if he's working, be "
    "crisp and get to the point fast.\n\n"
    "Be direct and honest. If he's wrong, missing something, or about to make "
    "a bad call, say so plainly and say why — he prefers blunt truth over "
    "diplomatic softening. Don't pad, don't over-hedge, don't flatter.\n\n"
    "Lead with the answer, then context only if needed — never bury the point "
    "under preamble. Keep responses as short as the question allows.\n\n"
    "You have access to memories about Aryaan from past conversations. Use them "
    "naturally to be useful and specific, but never recite them at him or "
    "announce that you're remembering — just let them inform what you say. If "
    "you don't know something, say so rather than guessing.\n\n"
    "When he asks you to take an action that sends, posts, spends, or deletes, "
    "confirm before doing it."
)
N_EXCHANGES = 10
DECAY = 0.995 / 24  # ≈ 0.995 / 24h
RETRIEVAL_DEBUG = True  # set False to silence retrieval logs

init_db()


# ---------------------------------------------------------------------------
# Plumbing: load / save
# ---------------------------------------------------------------------------

def load_messages() -> list[dict]:
    reflections = get_reflections()
    system_content = SYSTEM_PROMPT
    if reflections:
        joined = "\n".join(f"- {r}" for r in reflections)
        system_content += f"\n\nWhat you know about the user:\n{joined}"

    recent = get_messages_for_context(N_EXCHANGES)
    return [{"role": "system", "content": system_content}] + recent


def save_message(role: str, content: str):
    ts = time.time()
    msg_id = insert_message(role, content, ts)
    upsert(msg_id, content)
    _rate_importance(msg_id, content)


# ---------------------------------------------------------------------------
# Plumbing: importance rating
# ---------------------------------------------------------------------------

def _rate_importance(msg_id: int, content: str):
    # WRITE YOUR PROMPT HERE.
    # The goal: ask the LLM to rate how important this message is to remember
    # as a personal secretary (0 = trivial small talk, 10 = critical personal
    # fact — goals, preferences, relationships, decisions).
    # Guidelines for a good prompt:
    #   - Give the model a concrete scale (0 = trivial, 10 = critical)
    #   - Tell it what "important" means for a secretary context
    #   - Ask it to respond with a single number only (makes parsing easy)
    #   - Keep it short — this fires on every message

    prompt = """ As a personal secretary for Aryaan and his interests, rate how important this message is
    in terms of how it is relevant to Aryaan's life and interests. 0 is trivial small talk that isn't relevant and random in nature. 10 is a critical personal fact that is relevant to Aryaan's life and interests.


Message: {content}

Respond with a single integer 0-10.""".format(content=content)

    try:
        score = _call_rating(prompt)
        update_importance(msg_id, score)
    except Exception:
        # Non-fatal: importance defaults to NULL, scoring treats NULL as midpoint
        pass


def _call_rating(prompt: str) -> float:
    payload = json.dumps({
        "model": BASE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode()
    req = Request(
        f"{OLLAMA_HOST}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        text = json.loads(resp.read())["message"]["content"].strip()
    # Extract the first number found in the response
    for token in text.split():
        try:
            val = float(token.strip(".,"))
            return max(0.0, min(10.0, val))
        except ValueError:
            continue
    return 5.0  # fallback midpoint if parsing fails


# ---------------------------------------------------------------------------
# YOUR CODE: semantic retrieval + scoring
# ---------------------------------------------------------------------------

def retrieve(query: str, n: int) -> list[dict]:
    """Return [system_msg] + top-n scored memories for this query.

    You have access to:

      query_similar(query, n*3)
          → list of (msg_id: int, cos_distance: float)
          Cosine distance: 0.0 = identical, 2.0 = opposite.
          Over-fetch (n*3) so the scorer can re-rank.

      get_messages_by_ids(ids)
          → dict[msg_id → {"id", "role", "content", "timestamp", "importance_score"}]
          timestamp: Unix epoch (seconds). importance_score: 0-10 or None.

      time.time()
          → current Unix epoch for computing hours_elapsed.

      math.exp(x)
          → for the recency decay formula.

    Scoring formula (Generative Agents pattern):
        hours_elapsed  = (time.time() - msg["timestamp"]) / 3600
        recency        = math.exp(-DECAY * hours_elapsed)   # DECAY ≈ 0.995 / 24h
        importance     = (msg["importance_score"] or 5.0) / 10.0
        relevance      = 1.0 - cos_distance                 # flip distance → similarity
        score          = (recency + importance + relevance) / 3.0

    Return shape must match the M1 shape:
        [{"role": "system", "content": ...}] + [{"role": ..., "content": ...}, ...]
    so that constant-chat.py's chat() call needs zero changes.
    """

    system_msg = [load_messages()[0]]
    memories = []
    similar_queries = query_similar(query, n * 3)
    messages_by_ids = get_messages_by_ids([msg_id for msg_id, _ in similar_queries])
    now = time.time()

    if RETRIEVAL_DEBUG:
        print(f"\n[RETRIEVE] query: {query!r}")
        print(f"[RETRIEVE] chroma returned {len(similar_queries)} candidates:")

    for msg_id, cos_distance in similar_queries:
        msg = messages_by_ids.get(msg_id)
        if msg is None:
            continue
        if cos_distance > 0.5:
            continue
        hours_elapsed = (now - msg["timestamp"]) / 3600
        recency = math.exp(-DECAY * hours_elapsed)
        importance = (msg["importance_score"] or 5.0) / 10.0
        relevance = 1.0 - cos_distance
        score = (0.1*recency + 0.2*importance + 0.7*relevance)
        memories.append({"role": msg["role"], "content": msg["content"], "score": score})

        if RETRIEVAL_DEBUG:
            snippet = msg["content"][:80].replace("\n", " ")
            print(
                f"  id={msg_id} dist={cos_distance:.3f} "
                f"rec={recency:.3f} imp={importance:.3f} rel={relevance:.3f} "
                f"→ score={score:.3f} | {msg['role']}: {snippet!r}"
            )

    memories.sort(key=lambda x: x["score"], reverse=True)
    selected = memories[:n]

    if RETRIEVAL_DEBUG:
        print(f"[RETRIEVE] top-{n} selected:")
        for m in selected:
            print(f"  score={m['score']:.3f} | {m['role']}: {m['content'][:80].replace(chr(10), ' ')!r}")
        print()

    return system_msg + [{"role": m["role"], "content": m["content"]} for m in selected]



