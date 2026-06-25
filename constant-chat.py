"""Terminal playground REPL — NOT part of the served system.

A thin scratch surface for exercising the shared AgentRuntime + MCP tools from the
terminal. It shares the one agent core (agent_runtime.py) the server and worker use,
so there is no duplicate agent logic to maintain. The real product is server.py +
worker.py + frontend/.
"""

from agent_runtime import AgentRuntime, get_filesystem_server_args
from mcp_client import MCPClient
from memory import BASE_MODEL, N_EXCHANGES, save_message, retrieve
from reflect import run_reflection

EXIT_COMMANDS = {"exit", "quit", "q"}


def main():
    run_reflection()

    mcp = MCPClient("npx", get_filesystem_server_args())
    mcp.start()                      # plumbing: spawn server + open the session
    runtime = AgentRuntime()
    registered = runtime.register_mcp_read_tools(mcp)
    print(f"Registered read tools: {', '.join(registered) or 'none'}")

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
            assistant_content = runtime.run(window).strip()
        except RuntimeError as error:
            print(f"Error: {error}")
            continue

        if not assistant_content:
            print("Assistant: [No response returned]")
            continue

        save_message("user", user_input)
        save_message("assistant", assistant_content)
        print(f"Assistant: {assistant_content}")

    mcp.stop()


if __name__ == "__main__":
    main()
