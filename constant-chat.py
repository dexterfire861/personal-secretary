import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memory import (
    BASE_MODEL, CONTEXT_FILE, OLLAMA_HOST, N_EXCHANGES,
    load_messages, save_messages, retrieve,
)

EXIT_COMMANDS = {"exit", "quit", "q"}


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


def chat(messages):
    return post_ollama(
        "/api/chat",
        {"model": BASE_MODEL, "messages": messages, "stream": False},
    )


def main():
    try:
        messages = load_messages()
    except RuntimeError as error:
        print(f"Error: {error}")
        return

    print(f"Chatting with {BASE_MODEL}. Type 'exit', 'quit', or 'q' to stop.")
    print(f"Context file: {CONTEXT_FILE.name}")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        if user_input.lower() in EXIT_COMMANDS:
            print("Goodbye.")
            break

        messages.append({"role": "user", "content": user_input})
        save_messages(messages)

        try:
            result = chat(retrieve(messages, N_EXCHANGES))
        except RuntimeError as error:
            messages.pop()
            save_messages(messages)
            print(f"Error: {error}")
            continue

        assistant_content = result.get("message", {}).get("content", "").strip()

        if not assistant_content:
            print("Assistant: [No response returned]")
            continue

        messages.append({"role": "assistant", "content": assistant_content})
        save_messages(messages)
        print(f"Assistant: {assistant_content}")


if __name__ == "__main__":
    main()
