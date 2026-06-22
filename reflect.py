"""Reflection: synthesize raw memories into durable insights about the user.

Called once at session start from constant-chat.py.
Reads the most recent messages from SQLite, sends them to the LLM with a
reflection prompt, then stores the result as a new entry in the reflections table.
"""

import json
import time
from urllib.request import Request, urlopen

from db import get_messages_for_context, insert_reflection, get_reflections
from memory import BASE_MODEL, OLLAMA_HOST

REFLECTION_WINDOW = 30  # number of recent messages to reflect over


def run_reflection():
    recent = get_messages_for_context(REFLECTION_WINDOW // 2)
    if len(recent) < 4:
        # Not enough material to reflect on yet
        return

    conversation_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in recent
    )

    known = get_reflections()
    known_text = "\n".join(f"- {k}" for k in known) if known else "(none yet)"

    # -----------------------------------------------------------------------
    # WRITE YOUR REFLECTION PROMPT HERE.
    # Goal: given the raw conversation turns, produce 3-5 short bullet points
    # of durable, high-level facts about the user — the kind a good secretary
    # would carry forward indefinitely.
    # Guidelines:
    #   - Focus on persistent facts: goals, preferences, relationships, constraints
    #   - Ignore transient details: what they had for lunch, a one-off question
    #   - Each bullet should be a single, crisp sentence
    #   - Do NOT repeat facts already well-established; only surface what's new
    #   - If nothing notable was learned in this window, say "Nothing new to note."
    # -----------------------------------------------------------------------

    prompt = """You are a memory-extraction analyst. Read the conversation below and \
identify durable facts worth remembering about the user long-term. You are NOT having \
a conversation — you are extracting structured facts for a secretary's memory that will improve your ability to serve the user.


# Your task:
Extract durable facts about the user: their goals, preferences, relationships, and \
constraints. Critically, infer the STANDING fact behind a transient detail rather than \
recording the detail itself. Example: if the user asks about a heap problem, the durable \
fact is "preparing for technical interviews," NOT "asked about heaps." Always generalize \
to the lasting truth the exchange implies. Additionally, if the user is asking about a specific topic, you should extract the fact that they are interested in that topic and bring about relevant information.

# Rules:
- Record persistent facts, not transient ones (ignore one-off questions, passing mentions).
- Only surface what is NEW, or what UPDATES or CONTRADICTS an already-known fact. Do not \
repeat facts already listed above.
- If a new fact supersedes an old one, state the new fact (e.g. an accepted job offer \
replaces "interviewing").
- One crisp sentence per fact. At most 5 facts.

# Output format:
Output one fact per line. No numbering, no bullets, no preamble, no commentary. \
If nothing durable was learned, output exactly: NOTHING_NEW

# Already known about the user (do not repeat these; only surface what is new, updated, or contradicted):
{known}

Conversation:
{conversation}

Insights:""".format(conversation=conversation_text, known=known_text)

    try:
        insights = _call_llm(prompt)
        if insights and "NOTHING_NEW" not in insights.upper():
            insert_reflection(insights, time.time())
            print(f"[Reflection saved]")
    except Exception as e:
        print(f"[Reflection failed: {e}]")


def _call_llm(prompt: str) -> str:
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
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["message"]["content"].strip()
