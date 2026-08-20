from sqlalchemy import select

from app.database import SessionLocal
from app.models import Rota, Usuario, Veiculo, Organizacao, Perfil, StatusRota


def _login(client, email, password="123456"):
    response = client.post("/api/auth/login", json={"email": email, "senha": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_route_detail_includes_related_display_objects(client, admin_headers):
    with SessionLocal() as db:
        organization = db.scalar(select(Organizacao).order_by(Organizacao.id))
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).order_by(Usuario.id))
        vehicle = db.scalar(select(Veiculo).where(Veiculo.organizacao_id == organization.id).order_by(Veiculo.id))
        route = Rota(
            nome="Rota contrato detalhe",
            descricao="Teste",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            veiculo_id=vehicle.id if vehicle else None,
            status=StatusRota.FINALIZADA,
        )
        db.add(route)
        db.commit()
        db.refresh(route)
        route_id = route.id
        expected = {
            "organization": organization.nome,
            "driver": driver.nome,
            "vehicle": vehicle,
        }

    response = client.get(f"/api/rotas/{route_id}", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["organizacao"]["id"] == payload["organizacao_id"]
    assert payload["organizacao"]["nome"] == expected["organization"]
    assert payload["motorista"]["id"] == payload["motorista_id"]
    assert payload["motorista"]["nome"] == expected["driver"]
    if expected["vehicle"]:
        assert payload["veiculo"]["id"] == payload["veiculo_id"]
        assert payload["veiculo"]["placa"] == expected["vehicle"].placa
        assert payload["veiculo"]["modelo"] == expected["vehicle"].modelo
        assert payload["veiculo"]["marca"] == expected["vehicle"].marca


def test_auth_me_includes_related_organization(client, admin_headers):
    with SessionLocal() as db:
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).where(Usuario.organizacao_id.is_not(None)).order_by(Usuario.id))
        assert driver is not None
        organization = db.get(Organizacao, driver.organizacao_id)
        email = driver.email

    response = client.get("/api/auth/me", headers=_login(client, email))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["organizacao_id"] == organization.id
    assert payload["organizacao"]["id"] == organization.id
    assert payload["organizacao"]["nome"] == organization.nome
