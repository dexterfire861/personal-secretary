import json
import os
import socket
import time
import traceback

from agent_runtime import (
    AgentCancelled,
    AgentRuntime,
    get_filesystem_root,
    get_filesystem_server_args,
)
from db import (
    add_task_event,
    claim_next_task,
    init_db,
    set_task_cancelled,
    set_task_completed,
    set_task_failed,
    task_cancel_requested,
    update_worker_heartbeat,
)
from mcp_client import MCPClient
from memory import N_EXCHANGES, retrieve

POLL_SECONDS = 2.0
EVENT_PAYLOAD_LIMIT = 12000


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _safe_payload(payload: dict | None) -> str | None:
    if payload is None:
        return None
    safe = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > EVENT_PAYLOAD_LIMIT:
            safe[key] = value[:EVENT_PAYLOAD_LIMIT] + "\n...[truncated]"
        else:
            safe[key] = value
    return json.dumps(safe, ensure_ascii=True)


def _task_messages(prompt: str) -> list[dict]:
    messages = retrieve(prompt, N_EXCHANGES)
    messages.append(
        {
            "role": "user",
            "content": (
                "Background delegated task. Use only read-only tools. "
                "Do not write files, send messages, spend money, post content, "
                "or take external actions. If a future write/action is needed, "
                "describe the proposed action for approval instead.\n\n"
                f"Task: {prompt}"
            ),
        }
    )
    return messages


class Worker:
    def __init__(self):
        self.worker_id = _worker_id()
        self.runtime = AgentRuntime()
        self.mcp: MCPClient | None = None
        self.mcp_error: str | None = None

    def start_tools(self):
        try:
            self.mcp = MCPClient("npx", get_filesystem_server_args())
            self.mcp.start()
            registered = self.runtime.register_mcp_read_tools(self.mcp)
            info = {
                "filesystem_root": get_filesystem_root(),
                "registered_tools": registered,
            }
            update_worker_heartbeat(self.worker_id, "idle", info=json.dumps(info))
        except Exception as error:
            self.mcp_error = str(error)
            update_worker_heartbeat(
                self.worker_id,
                "degraded",
                info=json.dumps({"mcp_error": self.mcp_error}),
            )

    def stop(self):
        if self.mcp is not None:
            self.mcp.stop()

    def run_forever(self):
        init_db()
        self.start_tools()
        while True:
            self.run_once()
            time.sleep(POLL_SECONDS)

    def run_once(self) -> bool:
        update_worker_heartbeat(self.worker_id, "idle", info=self._heartbeat_info())
        task = claim_next_task(self.worker_id)
        if task is None:
            return False

        task_id = task["id"]
        update_worker_heartbeat(
            self.worker_id,
            "running",
            current_task_id=task_id,
            info=self._heartbeat_info(),
        )
        add_task_event(
            task_id,
            "started",
            "Worker claimed task.",
            _safe_payload({"worker_id": self.worker_id}),
        )

        try:
            if self.mcp_error:
                raise RuntimeError(f"Filesystem MCP unavailable: {self.mcp_error}")
            if task_cancel_requested(task_id):
                raise AgentCancelled("Task was cancelled before execution.")

            messages = _task_messages(task["prompt"])

            def emit(event_type: str, message: str, payload: dict | None = None):
                add_task_event(task_id, event_type, message, _safe_payload(payload))
                update_worker_heartbeat(
                    self.worker_id,
                    "running",
                    current_task_id=task_id,
                    info=self._heartbeat_info(),
                )

            result = self.runtime.run(
                messages,
                emit=emit,
                should_cancel=lambda: task_cancel_requested(task_id),
            )
            set_task_completed(task_id, result)
            add_task_event(
                task_id,
                "completed",
                "Task completed.",
                _safe_payload({"final_result": result}),
            )
        except AgentCancelled as error:
            set_task_cancelled(task_id, str(error))
            add_task_event(task_id, "cancelled", str(error))
        except Exception as error:
            set_task_failed(task_id, str(error))
            add_task_event(
                task_id,
                "failed",
                str(error),
                _safe_payload({"traceback": traceback.format_exc()}),
            )
        finally:
            update_worker_heartbeat(self.worker_id, "idle", info=self._heartbeat_info())
        return True

    def _heartbeat_info(self) -> str:
        return json.dumps(
            {
                "filesystem_root": get_filesystem_root(),
                "mcp_error": self.mcp_error,
                "tools": list(self.runtime.tool_registry.keys()),
            }
        )


def main():
    worker = Worker()
    try:
        worker.run_forever()
    finally:
        worker.stop()


if __name__ == "__main__":
    main()
