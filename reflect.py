"""Reflection: synthesize raw memories into durable insights about the user.

Called once at session start from constant-chat.py.
Reads the most recent messages from SQLite, sends them to the LLM with a
reflection prompt, then stores the result as a new entry in the reflections table.
"""

import json
import time
from urllib.request import Request, urlopen

from db import get_messages_for_context, insert_reflection
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

    prompt = """WRITE YOUR REFLECTION PROMPT HERE.

Conversation:
{conversation}

Insights:""".format(conversation=conversation_text)

    try:
        insights = _call_llm(prompt)
        if insights and "nothing new" not in insights.lower():
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
