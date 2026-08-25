from fastapi.testclient import TestClient
from app.database import SessionLocal
from app.models import Usuario
from app.security import create_token
from app.main import app


def test_simple_ws_connect():
    with TestClient(app) as client:
        with SessionLocal() as db:
            token = create_token(db.query(Usuario).filter(Usuario.email == "admin@sistema.com").one())
        with client.websocket_connect('/ws/tracking', headers={"Authorization": f"Bearer {token}"}) as websocket:
            websocket.send_json({'type': 'hello'})
            assert websocket is not None
