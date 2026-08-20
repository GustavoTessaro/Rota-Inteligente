from sqlalchemy import select

from app.database import SessionLocal
from app.models import Endereco, Entrega, Organizacao, Perfil, Pedido, Rota, RotaEntrega, StatusEntrega, StatusRota, Usuario


def _login(client, email, password="123456"):
    response = client.post("/api/auth/login", json={"email": email, "senha": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _create_route(client, status=StatusRota.PRONTA):
    with SessionLocal() as db:
        driver = db.scalar(select(Usuario).where(Usuario.perfil == Perfil.MOTORISTA).order_by(Usuario.id))
        organization = db.get(Organizacao, driver.organizacao_id)
        address = db.scalar(select(Endereco).order_by(Endereco.id))
        order = db.scalar(select(Pedido).order_by(Pedido.id))
        delivery = Entrega(
            pedido_id=order.id,
            entregador_id=driver.id,
            endereco_origem_id=address.id,
            endereco_destino_id=address.id,
            status=StatusEntrega.AGUARDANDO_COLETA,
        )
        route = Rota(
            nome=f"Teste evento {status.value}",
            descricao="Teste",
            organizacao_id=organization.id,
            motorista_id=driver.id,
            status=status,
            carga_confirmada=True,
        )
        db.add_all([delivery, route])
        db.flush()
        db.add(RotaEntrega(rota_id=route.id, entrega_id=delivery.id, ordem_visita=1, sequencia_otimizada=1))
        db.commit()
        return route.id, driver.email


def _last_history(client, route_id, headers):
    response = client.get(f"/api/rotas/{route_id}/historico", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()[-1]


def test_pronta_to_em_execucao_logs_partida(client):
    route_id, email = _create_route(client)
    headers = _login(client, email)
    response = client.patch(f"/api/rotas/{route_id}/status", headers=headers, json={"status": "EM_EXECUCAO"})
    assert response.status_code == 200, response.text
    assert _last_history(client, route_id, headers)["evento"] == "PARTIDA"


def test_em_execucao_to_pausada_logs_pausa(client):
    route_id, email = _create_route(client, StatusRota.EM_EXECUCAO)
    headers = _login(client, email)
    response = client.patch(f"/api/rotas/{route_id}/status", headers=headers, json={"status": "PAUSADA"})
    assert response.status_code == 200, response.text
    assert _last_history(client, route_id, headers)["evento"] == "PAUSA"


def test_pausada_to_em_execucao_logs_retomada(client):
    route_id, email = _create_route(client, StatusRota.PAUSADA)
    headers = _login(client, email)
    response = client.patch(f"/api/rotas/{route_id}/status", headers=headers, json={"status": "EM_EXECUCAO"})
    assert response.status_code == 200, response.text
    assert _last_history(client, route_id, headers)["evento"] == "RETOMADA"


def test_em_execucao_to_finalizada_logs_finalizada_completion(client):
    route_id, email = _create_route(client, StatusRota.EM_EXECUCAO)
    headers = _login(client, email)
    response = client.patch(f"/api/rotas/{route_id}/status", headers=headers, json={"status": "FINALIZADA"})
    assert response.status_code == 200, response.text
    assert _last_history(client, route_id, headers)["evento"] == "FINALIZADA"


def test_em_execucao_to_cancelada_logs_cancelamento(client):
    route_id, email = _create_route(client, StatusRota.EM_EXECUCAO)
    headers = _login(client, email)
    response = client.patch(f"/api/rotas/{route_id}/status", headers=headers, json={"status": "CANCELADA"})
    assert response.status_code == 200, response.text
    assert _last_history(client, route_id, headers)["evento"] == "CANCELAMENTO"
