from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Entrega, Organizacao, Pedido, Rota, RotaEntrega, StatusEntrega, StatusRota, StatusVeiculo, Usuario, Veiculo


def test_dashboard_endpoint_returns_live_metrics(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        vehicle = db.scalar(select(Veiculo).order_by(Veiculo.id))
        assert vehicle is not None
        vehicle.status = StatusVeiculo.DISPONIVEL

        driver = db.scalar(select(Usuario).where(Usuario.perfil == "MOTORISTA").order_by(Usuario.id))
        assert driver is not None
        driver.ativo = True

        organization = db.get(Organizacao, vehicle.organizacao_id)
        order = db.scalar(select(Pedido).order_by(Pedido.id))
        assert order is not None
        order.organizacao_id = organization.id

        delayed_delivery = Entrega(
            pedido_id=order.id,
            entregador_id=driver.id,
            endereco_origem_id=1,
            endereco_destino_id=1,
            status=StatusEntrega.EM_ROTA,
            previsao_entrega=datetime.now() - timedelta(minutes=10),
            data_coleta=datetime.now() - timedelta(minutes=15),
            observacoes="atrasada",
        )
        db.add(delayed_delivery)
        db.commit()
        db.refresh(delayed_delivery)

        route = Rota(
            nome="Rota do dashboard",
            descricao="Rota criada pelo teste",
            organizacao_id=organization.id,
            veiculo_id=vehicle.id,
            motorista_id=driver.id,
            status=StatusRota.EM_EXECUCAO,
        )
        db.add(route)
        db.flush()
        db.add(RotaEntrega(rota_id=route.id, entrega_id=delayed_delivery.id, ordem_visita=1, sequencia_otimizada=1))
        db.commit()

    response = client.get('/api/relatorios/dashboard', headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data['entregas_andamento'] >= 1
    assert data['entregas_atrasadas'] >= 1
    assert data['rotas_em_execucao'] >= 1
    assert data['veiculos_disponiveis'] >= 1
    assert data['motoristas_ativos'] >= 1
