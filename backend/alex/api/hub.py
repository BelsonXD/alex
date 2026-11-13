"""Fan-out to connected interfaces. One lock per socket so sends don't interleave."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self._clients: dict[int, tuple[WebSocket, asyncio.Lock]] = {}

    def add(self, ws: WebSocket) -> None:
        self._clients[id(ws)] = (ws, asyncio.Lock())

    def discard(self, ws: WebSocket) -> None:
        self._clients.pop(id(ws), None)

    async def send(self, ws: WebSocket, payload: dict[str, Any]) -> None:
        item = self._clients.get(id(ws))
        if item is None:
            return
        socket, lock = item
        async with lock:
            await socket.send_json(payload)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        for socket, lock in list(self._clients.values()):
            try:
                async with lock:
                    await socket.send_json(payload)
            except Exception:
                self.discard(socket)
