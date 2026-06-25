"""Shared synchronous agent runtime for chat, REPL, and background tasks."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp_client import MCPClient
from memory import BASE_MODEL, OLLAMA_HOST

MAX_TOOL_ITERATIONS = 5
READ_TOOL_ALLOWLIST = {"read_text_file", "list_directory", "search_files"}
DEFAULT_FS_ROOT = str(Path.home())


class AgentRuntimeError(RuntimeError):
    pass


class AgentCancelled(RuntimeError):
    pass


def get_filesystem_root() -> str:
    return os.path.realpath(os.environ.get("SECRETARY_FS_ROOT", DEFAULT_FS_ROOT))


def get_filesystem_server_args() -> list[str]:
    return ["-y", "@modelcontextprotocol/server-filesystem", get_filesystem_root()]


def get_time() -> str:
    return datetime.now().strftime("%A %Y-%m-%d %H:%M:%S")


def post_ollama(path: str, payload: dict) -> dict:
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
        raise AgentRuntimeError(f"{path} failed with {error.code}: {body}") from error
    except URLError as error:
        raise AgentRuntimeError(
            f"Could not reach Ollama at {OLLAMA_HOST}. Is `ollama serve` running?"
        ) from error


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    payload = {"model": BASE_MODEL, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    return post_ollama("/api/chat", payload)


class AgentRuntime:
    def __init__(self):
        self.tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get the current local date and time.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            }
        ]
        self.tool_registry = {"get_time": lambda: get_time()}

    def register_mcp_read_tools(self, client: MCPClient) -> list[str]:
        registered = []
        for tool in client.list_tools():
            if tool.name not in READ_TOOL_ALLOWLIST:
                continue
            self.tool_schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                }
            )
            self.tool_registry[tool.name] = self._make_mcp_tool(client, tool.name)
            registered.append(tool.name)
        return registered

    @staticmethod
    def _make_mcp_tool(client: MCPClient, name: str) -> Callable[..., str]:
        def call_tool(**kwargs):
            return client.call_tool(name, kwargs)

        return call_tool

    def dispatch(self, tool_call: dict) -> str:
        tool_name = tool_call["function"]["name"]
        if tool_name not in self.tool_registry:
            return f"Error: unknown tool {tool_name}"
        arguments = tool_call["function"].get("arguments") or {}
        return str(self.tool_registry[tool_name](**arguments))

    def run(
        self,
        messages: list[dict],
        emit: Callable[[str, str, dict | None], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        emit = emit or (lambda _event_type, _message, _payload=None: None)
        should_cancel = should_cancel or (lambda: False)

        for iteration in range(MAX_TOOL_ITERATIONS):
            if should_cancel():
                raise AgentCancelled("Task was cancelled before the next model step.")

            emit(
                "model_step",
                f"Calling {BASE_MODEL} for iteration {iteration + 1}.",
                {"iteration": iteration + 1, "tools": list(self.tool_registry.keys())},
            )
            result = chat(messages, tools=self.tool_schemas)
            msg = result["message"]

            if msg.get("tool_calls"):
                tool_calls = msg["tool_calls"]
                messages.append(msg)
                emit(
                    "assistant_tool_plan",
                    f"Model requested {len(tool_calls)} tool call(s).",
                    {"tool_calls": tool_calls},
                )
                for call in tool_calls:
                    if should_cancel():
                        raise AgentCancelled("Task was cancelled before a tool call.")
                    tool_name = call["function"]["name"]
                    arguments = call["function"].get("arguments") or {}
                    emit(
                        "tool_call",
                        f"Calling tool: {tool_name}",
                        {"name": tool_name, "arguments": arguments},
                    )
                    output = self.dispatch(call)
                    emit(
                        "tool_result",
                        f"Tool returned {len(output)} characters.",
                        {"name": tool_name, "output": output},
                    )
                    messages.append({"role": "tool", "content": output})
                continue

            content = msg.get("content", "")
            if content:
                emit("final", "Model returned a final answer.", {"content": content})
                return content

        raise AgentRuntimeError("Max tool iterations reached")
