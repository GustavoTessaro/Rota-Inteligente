import os

os.environ["DATABASE_URL"] = "sqlite:///./test_entregas.db"
os.environ["SEED_DATABASE"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)


@pytest.fixture()
def admin_headers(client):
    response = client.post("/api/auth/login", json={
        "email": "admin@sistema.com", "senha": "123456",
    })
    return {"Authorization": f'Bearer {response.json()["token"]}'}
