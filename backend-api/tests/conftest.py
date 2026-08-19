import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEVELOPMENT_DATABASE_URL = "sqlite:///./test_entregas.db"
PYTEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"rota_inteligente_pytest_{os.getpid()}.db"
PYTEST_DATABASE_URL = f"sqlite:///{PYTEST_DATABASE_PATH.as_posix()}"

assert PYTEST_DATABASE_URL != DEVELOPMENT_DATABASE_URL
os.environ["DATABASE_URL"] = PYTEST_DATABASE_URL
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
