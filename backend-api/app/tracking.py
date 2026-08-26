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
        print(f"[TRACKING_WS] conectado perfil={connection.perfil.value} organizacao={connection.organizacao_id}")

    def disconnect(self, websocket: WebSocket) -> None:
        connection = next((item for item in self.active_connections if item.websocket is websocket), None)
        self.active_connections = [item for item in self.active_connections if item.websocket is not websocket]
        if connection is not None:
            print(f"[TRACKING_WS] desconectado perfil={connection.perfil.value} organizacao={connection.organizacao_id}")

    async def broadcast(self, message: dict[str, Any], organization_id: int | None = None) -> None:
        async with self._lock:
            dead_connections: list[WebSocket] = []
            print(f"[TRACKING_WS] broadcast organizacao={organization_id} conexoes={len(self.active_connections)}")
            for connection in list(self.active_connections):
                if connection.perfil == Perfil.GESTOR and connection.organizacao_id != organization_id:
                    continue
                try:
                    await connection.websocket.send_json(message)
                    print(f"[TRACKING_WS] enviado para cliente perfil={connection.perfil.value} organizacao={connection.organizacao_id}")
                except Exception:
                    dead_connections.append(connection.websocket)
            for websocket in dead_connections:
                self.disconnect(websocket)
            if not self.active_connections:
                print("[TRACKING_WS] nenhuma conexão ativa")


manager = ConnectionManager()
