from fastapi.testclient import TestClient


def login_driver(client: TestClient, route: dict) -> dict:
    driver = route.get("motorista") or {}
    response = client.post(
        "/api/auth/login",
        json={"email": driver["email"], "senha": "123456"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def select_alternative(client: TestClient, route: dict, criterion: str = "MAIS_CURTA") -> dict:
    headers = login_driver(client, route)
    alternative = next(item for item in route["alternativas"] if item["criterio"] == criterion)
    response = client.post(
        f"/api/rotas/{route['id']}/selecionar-alternativa",
        headers=headers,
        json={"alternativa_id": alternative["id"]},
    )
    assert response.status_code == 200, response.text
    return response.json()
