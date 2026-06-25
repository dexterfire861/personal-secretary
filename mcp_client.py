"""Synchronous facade over the (async) MCP Python SDK.  [PLUMBING — rented infra]

Why this exists: the MCP SDK is async (`async with stdio_client`, `await
session.call_tool`), but the secretary's REPL/agent loop is synchronous and the
server must stay alive across many turns (respawning npx per call is slow and
stateless). So we run one persistent MCP session inside a background event-loop
thread and expose blocking `list_tools()` / `call_tool()` methods that the sync
loop can call directly.

You don't need to study this to understand the secretary — it's event-loop
plumbing. The interesting part (bridging tools into the model, routing dispatch)
lives in constant-chat.py and is yours to write.
"""

import asyncio
import threading

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self, command: str, args: list[str]):
        self._params = StdioServerParameters(command=command, args=args)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._session: ClientSession | None = None
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        self._stop: asyncio.Event | None = None

    # -- background thread: owns the event loop and the live session ----------

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:  # surfaced to start() via _ready
            self._startup_error = e
            self._ready.set()

    async def _serve(self):
        self._stop = asyncio.Event()
        async with stdio_client(self._params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                self._ready.set()          # session is live; start() may return
                await self._stop.wait()     # keep the session open until stop()

    # -- sync API for the agent loop ------------------------------------------

    def start(self, timeout: float = 60.0):
        """Launch the server + session; block until it's ready (or fail)."""
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("MCP server did not become ready in time")
        if self._startup_error:
            raise self._startup_error

    def list_tools(self):
        """Return the live list of Tool objects (.name, .description, .inputSchema)."""
        fut = asyncio.run_coroutine_threadsafe(self._session.list_tools(), self._loop)
        return fut.result(timeout=30).tools

    def call_tool(self, name: str, arguments: dict | None) -> str:
        """Call an MCP tool, return its text content as a single string.

        On a tool error the server returns the error as text content, so the
        model sees what went wrong rather than the loop crashing.
        """
        coro = self._session.call_tool(name, arguments or {})
        result = asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=60)
        parts = [getattr(c, "text", str(c)) for c in result.content]
        return "\n".join(parts)

    def stop(self):
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
