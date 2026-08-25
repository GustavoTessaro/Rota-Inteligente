from __future__ import annotations

import asyncio
from typing import Any
from dataclasses import dataclass
from .models import Perfil
from fastapi import WebSocket, WebSocketDisconnect


@dataclass
class TrackingConnection:
    websocket: WebSocket
    user_id: int
    perfil: Perfil
    organizacao_id: int | None


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[TrackingConnection] = []
        self._lock = asyncio.Lock()

    async def connect(self, connection: TrackingConnection) -> None:
        websocket = connection.websocket
        await websocket.accept()
        self.active_connections.append(connection)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections = [item for item in self.active_connections if item.websocket is not websocket]

    async def broadcast(self, message: dict[str, Any], organization_id: int | None = None) -> None:
        async with self._lock:
            dead_connections: list[WebSocket] = []
            for connection in list(self.active_connections):
                if connection.perfil == Perfil.GESTOR and connection.organizacao_id != organization_id:
                    continue
                try:
                    await connection.websocket.send_json(message)
                except Exception:
                    dead_connections.append(connection.websocket)
            for websocket in dead_connections:
                self.disconnect(websocket)


manager = ConnectionManager()
