import json
from pathlib import Path
from urllib.request import Request, urlopen

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

OLLAMA_HOST = "http://localhost:11434"
BASE_MODEL = "llama3.1:8b"
SYSTEM_PROMPT = "You are a concise personal secretary."
CONTEXT_FILE = Path(__file__).with_name("chat-context.json")
N_EXCHANGES = 10

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- memory (same logic as constant-chat.py; extract to memory.py at M2) ---

def load_messages():
    if not CONTEXT_FILE.exists():
        return [{"role": "system", "content": SYSTEM_PROMPT}]
    with CONTEXT_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    messages = data.get("messages", [])
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


# --- API ---

class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    messages = load_messages()
    messages.append({"role": "user", "content": req.message})
    save_messages(messages)

    window = retrieve(messages, N_EXCHANGES)
    accumulated = []

    def stream():
        payload = {"model": BASE_MODEL, "messages": window, "stream": True}
        request = Request(
            f"{OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=120) as resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                chunk = json.loads(line.decode("utf-8"))
                token = chunk.get("message", {}).get("content", "")
                if token:
                    accumulated.append(token)
                    yield token

        messages.append({"role": "assistant", "content": "".join(accumulated)})
        save_messages(messages)

    return StreamingResponse(stream(), media_type="text/plain")


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
