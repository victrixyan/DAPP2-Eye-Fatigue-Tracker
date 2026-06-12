"""WebSocket hub for broadcasting live session telemetry to connected clients."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from starlette.websockets import WebSocketState


class SessionHub:
    """Tracks open session sockets and fans out telemetry from the ML relay thread."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def register(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    def publish(self, payload: dict[str, Any]) -> None:
        """Thread-safe entry point used by the telemetry relay thread."""
        if self._loop is None or not self._clients:
            return
        message = json.dumps(payload)
        asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    async def _broadcast(self, message: str) -> None:
        stale: list[WebSocket] = []
        for client in list(self._clients):
            if client.client_state != WebSocketState.CONNECTED:
                stale.append(client)
                continue
            try:
                await client.send_text(message)
            except Exception:
                stale.append(client)

        for client in stale:
            self._clients.discard(client)


session_hub = SessionHub()


async def handle_session_ws(websocket: WebSocket) -> None:
    """Hold one browser connection open for the live session page."""
    loop = asyncio.get_running_loop()
    session_hub.bind_loop(loop)

    await session_hub.register(websocket)
    try:
        while True:
            # Keep the socket alive; pause/resume uses HTTP routes.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await session_hub.unregister(websocket)
