import json
from urllib.request import Request, urlopen

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from memory import BASE_MODEL, OLLAMA_HOST, N_EXCHANGES, save_message, retrieve

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
def chat_endpoint(req: ChatRequest):
    # Retrieve past context BEFORE saving current message so the current
    # message isn't in Chroma yet (which would make it appear first in the
    # window instead of last, causing the model to respond to past messages).
    window = retrieve(req.message, N_EXCHANGES)
    window.append({"role": "user", "content": req.message})
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

        response_text = "".join(accumulated)
        if response_text:
            save_message("user", req.message)
            save_message("assistant", response_text)

    return StreamingResponse(stream(), media_type="text/plain")


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
