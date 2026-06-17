import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_HOST = "http://localhost:11434"
BASE_MODEL = "llama3.1:8b"
CREATED_MODEL = "personal-secretary-demo"


def post_ollama(path, payload):
    request = Request(
        f"{OLLAMA_HOST}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8")
        raise RuntimeError(f"{path} failed with {error.code}: {body}") from error
    except URLError as error:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_HOST}. Is `ollama serve` running?"
        ) from error


def generate_post():
    return post_ollama(
        "/api/generate",
        {
            "model": BASE_MODEL,
            "prompt": "Write a concise morning briefing for a busy founder.",
            "stream": False,
        },
    )


def chat_post():
    return post_ollama(
        "/api/chat",
        {
            "model": BASE_MODEL,
            "messages": [
                {"role": "system", "content": "You are a concise personal secretary."},
                {"role": "user", "content": "Summarize my top three priorities today."},
            ],
            "stream": False,
        },
    )


def create_post():
    return post_ollama(
        "/api/create",
        {
            "model": CREATED_MODEL,
            "from": BASE_MODEL,
            "system": "You are a proactive personal secretary. Be brief, specific, and practical.",
            "stream": False,
        },
    )


def show_model_details_post(model=BASE_MODEL):
    return post_ollama(
        "/api/show",
        {
            "model": model,
        },
    )


def main():
    requests_to_run = [
        ("Generate POST", generate_post),
        ("Chat POST", chat_post),
        ("Create POST", create_post),
        ("Show Model Details POST", show_model_details_post),
    ]

    for label, run_request in requests_to_run:
        print(f"\n--- {label} ---")
        result = run_request()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
