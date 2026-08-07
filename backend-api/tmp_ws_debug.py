from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

app = FastAPI()

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.receive_text()

with TestClient(app) as client:
    with client.websocket_connect("/ws") as websocket:
        print("connected")
