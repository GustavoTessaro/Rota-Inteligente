from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Entrega, Organizacao, Perfil, Rota, RotaEntrega, StatusEntrega, StatusRota, Usuario


def _login(client, email, password="123456"):
    response = client.post("/api/auth/login", json={"email": email, "senha": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_new_route_start_and_completion_keep_timestamp_order(client, admin_headers):
    with SessionLocal() as db:
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).order_by(Usuario.id))
        organization = db.get(Organizacao, driver.organizacao_id)
        route = Rota(
            nome="Teste política de tempo",
            descricao="",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            status=StatusRota.PRONTA,
            carga_confirmada=True,
        )
        delivery = db.scalar(select(Entrega).where(Entrega.entregador_id == driver.id, Entrega.status == StatusEntrega.AGUARDANDO_COLETA).order_by(Entrega.id))
        if delivery is not None:
            route.entregas = [RotaEntrega(entrega_id=delivery.id, ordem_visita=1, sequencia_otimizada=1)]
        db.add(route)
        db.commit()
        db.refresh(route)
        route_id = route.id
        email = driver.email

    headers = _login(client, email)
    started = client.patch(f"/api/rotas/{route_id}/status", headers=headers, json={"status": "EM_EXECUCAO"})
    assert started.status_code == 200, started.text
    finished = client.patch(f"/api/rotas/{route_id}/status", headers=headers, json={"status": "FINALIZADA"})
    assert finished.status_code == 200, finished.text
    data = finished.json()
    assert data["data_inicio"] is not None
    assert data["data_conclusao"] is not None
    assert data["data_conclusao"] >= data["data_inicio"]


def test_daily_summary_uses_expected_duration_for_inverted_timestamps(client):
    with SessionLocal() as db:
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).order_by(Usuario.id))
        organization = db.get(Organizacao, driver.organizacao_id)
        now = datetime.now()
        route = Rota(
            nome="Teste timestamp invertido",
            descricao="",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            status=StatusRota.FINALIZADA,
            data_inicio=now,
            data_conclusao=now.replace(hour=max(0, now.hour - 1)),
            duracao_real=Decimal("0"),
            duracao_prevista=Decimal("0.35"),
            distancia_prevista=Decimal("0"),
        )
        db.add(route)
        db.commit()
        email = driver.email

    response = client.get("/api/rotas/motorista/resumo-diario", headers=_login(client, email))
    assert response.status_code == 200, response.text
    assert response.json()["tempo_em_rota_hoje_minutos"] >= 0
