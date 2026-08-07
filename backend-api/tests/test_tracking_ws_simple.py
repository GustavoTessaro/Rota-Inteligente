from fastapi.testclient import TestClient
from app.main import app


def test_simple_ws_connect():
    with TestClient(app) as client:
        with client.websocket_connect('/ws/tracking') as websocket:
            websocket.send_json({'type': 'hello'})
            assert websocket is not None
