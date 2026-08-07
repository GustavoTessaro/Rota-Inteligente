from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Entrega, Rota, StatusEntrega, StatusRota, StatusVeiculo, Usuario, Veiculo


def test_dashboard_endpoint_returns_live_metrics(client: TestClient, admin_headers: dict) -> None:
    with SessionLocal() as db:
        route = db.get(Rota, 1)
        assert route is not None

        vehicle = db.get(Veiculo, route.veiculo_id)
        assert vehicle is not None
        vehicle.status = StatusVeiculo.DISPONIVEL

        driver = db.get(Usuario, route.motorista_id)
        assert driver is not None
        driver.ativo = True

        delayed_delivery = Entrega(
            pedido_id=1,
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

        route.status = StatusRota.EM_EXECUCAO
        db.commit()

    response = client.get('/api/relatorios/dashboard', headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert data['entregas_andamento'] >= 1
    assert data['entregas_atrasadas'] >= 1
    assert data['rotas_em_execucao'] >= 1
    assert data['veiculos_disponiveis'] >= 1
    assert data['motoristas_ativos'] >= 1
