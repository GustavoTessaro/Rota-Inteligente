import asyncio
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tracking import manager


@pytest.fixture(autouse=True)
def clear_manager() -> None:
    manager.active_connections.clear()


def test_websocket_connection_and_broadcast() -> None:
    with TestClient(app) as client:
        with client.websocket_connect('/ws/tracking') as websocket:
            assert websocket is not None
            asyncio.run(manager.broadcast({"type": "ping", "payload": {"ok": True}}))
            msg = websocket.receive_json()
            assert msg["type"] == "ping"
            assert msg["payload"]["ok"] is True
