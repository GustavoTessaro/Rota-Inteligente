import asyncio
import sys
sys.path.insert(0, '.')

from fastapi.testclient import TestClient
from app.main import app
from app.tracking import manager

with TestClient(app) as client:
    with client.websocket_connect('/ws/tracking') as websocket:
        print('connected')
        asyncio.run(manager.broadcast({'type': 'ping', 'payload': {'ok': True}}))
        msg = websocket.receive_json()
        print('msg', msg)
