from __future__ import annotations

import asyncio
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            dead_connections: list[WebSocket] = []
            for connection in list(self.active_connections):
                try:
                    await connection.send_json(message)
                except Exception:
                    dead_connections.append(connection)
            for connection in dead_connections:
                self.disconnect(connection)


manager = ConnectionManager()
