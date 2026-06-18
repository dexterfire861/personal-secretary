import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memory import BASE_MODEL, OLLAMA_HOST, N_EXCHANGES, load_messages, save_message, retrieve
from reflect import run_reflection

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
    run_reflection()

    print(f"Chatting with {BASE_MODEL}. Type 'exit', 'quit', or 'q' to stop.")

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

        window = retrieve(user_input, N_EXCHANGES)
        window.append({"role": "user", "content": user_input})

        try:
            result = chat(window)
        except RuntimeError as error:
            print(f"Error: {error}")
            continue

        assistant_content = result.get("message", {}).get("content", "").strip()

        if not assistant_content:
            print("Assistant: [No response returned]")
            continue

        save_message("user", user_input)
        save_message("assistant", assistant_content)
        print(f"Assistant: {assistant_content}")


if __name__ == "__main__":
    main()
