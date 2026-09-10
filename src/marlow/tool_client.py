"""Tool transport. call() has no session: stdio owns its own."""

from __future__ import annotations

import atexit
import asyncio
import os
import sys
import threading
from typing import Any, Protocol

from mcp import Client, StdioServerParameters
from sqlalchemy.orm import Session

from marlow.codes import SOURCE_TRUST_UNTRUSTED_WEB_CONTENT
from marlow.db import _is_sqlite_memory
from marlow.faults import FaultHooks
from marlow.observation import Observation
from marlow.tools import execute_tool

TOOL_CLIENT_ENV = "MARLOW_TOOL_CLIENT"
TOOL_CLIENT_STDIO = "stdio"
DATABASE_URL_ENV = "MARLOW_DATABASE_URL"

_singleton_lock = threading.Lock()
_stdio_singleton: StdioMCPClient | None = None


class ToolClient(Protocol):
    def call(self, name: str, *, actor_id: str, **arguments: Any) -> Observation: ...


class InProcessToolClient:
    def __init__(self, session: Session, faults: FaultHooks | None = None) -> None:
        self._session = session
        self._faults = faults

    def call(self, name: str, *, actor_id: str, **arguments: Any) -> Observation:
        return execute_tool(self._session, name, actor_id=actor_id, faults=self._faults, **arguments)


class StdioMCPClient:
    def __init__(self, db_url: str) -> None:
        if _is_sqlite_memory(db_url):
            raise ValueError("StdioMCPClient cannot use an in-memory SQLite URL")
        self._db_url = db_url
        self._lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Client | None = None
        self._stop: asyncio.Event | None = None
        self._start_error: BaseException | None = None
        self._closed = False
        atexit.register(self.close)

    def call(self, name: str, *, actor_id: str, **arguments: Any) -> Observation:
        self._ensure_started()
        payload = {"actor_id": actor_id, **arguments}
        with self._call_lock:
            if self._client is None or self._loop is None:
                raise RuntimeError("StdioMCPClient is closed")
            future = asyncio.run_coroutine_threadsafe(self._client.call_tool(name, payload), self._loop)
            result = future.result(timeout=60)
        return _observation_from_mcp(result)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
            thread = self._thread
            stop = self._stop
            self._client = None
            self._loop = None
            self._thread = None
            self._stop = None
        if loop is not None and stop is not None:
            loop.call_soon_threadsafe(stop.set)
        if thread is not None:
            thread.join(timeout=15)

    def _ensure_started(self) -> None:
        with self._lock:
            if self._client is not None:
                return
            if self._closed:
                raise RuntimeError("StdioMCPClient is closed")
            ready = threading.Event()
            self._thread = threading.Thread(
                target=self._run_loop,
                args=(ready,),
                name="marlow-mcp-stdio",
            )
            self._thread.start()
        if not ready.wait(timeout=30):
            raise RuntimeError("StdioMCPClient failed to start")
        if self._start_error is not None:
            raise RuntimeError("StdioMCPClient failed to start") from self._start_error

    def _run_loop(self, ready: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def runner() -> None:
            stop = asyncio.Event()
            self._stop = stop
            try:
                params = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "marlow.ticket_mcp"],
                    env={DATABASE_URL_ENV: self._db_url},
                )
                async with Client(params) as client:
                    self._client = client
                    ready.set()
                    await stop.wait()
            except BaseException as exc:
                self._start_error = exc
                ready.set()
            finally:
                self._client = None
                loop.stop()

        loop.create_task(runner())
        loop.run_forever()
        loop.close()


def process_stdio_client(db_url: str) -> StdioMCPClient:
    global _stdio_singleton
    with _singleton_lock:
        if _stdio_singleton is None:
            _stdio_singleton = StdioMCPClient(db_url)
        elif _stdio_singleton._db_url != db_url:
            raise RuntimeError("StdioMCPClient already started with a different database URL")
        return _stdio_singleton


def resolve_tool_client(
    session: Session,
    faults: FaultHooks | None,
    override: ToolClient | None = None,
) -> ToolClient:
    if override is not None:
        return override
    if os.environ.get(TOOL_CLIENT_ENV) == TOOL_CLIENT_STDIO:
        url = os.environ.get(DATABASE_URL_ENV)
        if not url:
            raise RuntimeError(f"{DATABASE_URL_ENV} must be set when {TOOL_CLIENT_ENV}={TOOL_CLIENT_STDIO}")
        return process_stdio_client(url)
    return InProcessToolClient(session, faults)


def _observation_from_mcp(result: Any) -> Observation:
    payload = result.structured_content
    if not isinstance(payload, dict):
        raise RuntimeError("MCP tool result is not an Observation dict")
    return Observation(
        ok=bool(payload["ok"]),
        code=str(payload["code"]),
        retryable=bool(payload["retryable"]),
        source_trust=str(payload.get("source_trust") or SOURCE_TRUST_UNTRUSTED_WEB_CONTENT),
        data=payload.get("data"),
    )
