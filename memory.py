import json
from pathlib import Path

# Storage: JSON file (M1 format — migrate to SQLite at M2)
BASE_MODEL = "llama3.1:8b"
OLLAMA_HOST = "http://localhost:11434"
SYSTEM_PROMPT = "You are a concise personal secretary."
CONTEXT_FILE = Path(__file__).with_name("chat-context.json")
N_EXCHANGES = 10


def load_messages():
    if not CONTEXT_FILE.exists():
        return [{"role": "system", "content": SYSTEM_PROMPT}]
    with CONTEXT_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        raise RuntimeError(f"{CONTEXT_FILE.name} must contain a messages list.")
    if not messages or messages[0].get("role") != "system":
        messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    return messages


def save_messages(messages):
    data = {"model": BASE_MODEL, "messages": messages}
    with CONTEXT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def retrieve(messages, n):
    return [messages[0]] + messages[1:][-(n * 2):]
