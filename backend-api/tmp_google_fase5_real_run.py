import logging
import re
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import (
    Cliente,
    ComprovanteEntrega,
    Endereco,
    Entrega,
    HistoricoEntrega,
    Ocorrencia,
    Organizacao,
    Pedido,
    PedidoItem,
    Rota,
    RotaAlternativa,
    RotaEntrega,
    RotaHistorico,
    RotaPosicao,
    Usuario,
    Veiculo,
)


SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:key|api_key|access_token|token|authorization)=)[^&\s]+",
    re.IGNORECASE,
)


def redact_sensitive_text(value):
    return SENSITIVE_QUERY_RE.sub(r"\1[REDACTED]", value)


class SensitiveLogFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        record.msg = redact_sensitive_text(message)
        record.args = ()
        return True


def install_sensitive_log_redaction():
    redaction_filter = SensitiveLogFilter()
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).addFilter(redaction_filter)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redaction_filter)


def route_state(payload):
    deliveries = payload.get("entregas") or []
    ordered_deliveries = sorted(deliveries, key=lambda item: item["ordem_visita"])
    optimized_deliveries = sorted(
        (item for item in deliveries if item.get("sequencia_otimizada") is not None),
        key=lambda item: item["sequencia_otimizada"],
    )
    return {
        "selected_id": payload.get("alternativa_escolhida_id"),
        "can_start": payload.get("pode_iniciar"),
        "provisional_order": [item["id"] for item in ordered_deliveries],
        "official_delivery_sequence": [item["id"] for item in optimized_deliveries],
        "official_order": [item["entrega_id"] for item in optimized_deliveries],
        "distance": payload.get("distancia_prevista"),
        "duration": payload.get("duracao_prevista"),
        "geometry": payload.get("route_geometry"),
    }


install_sensitive_log_redaction()
settings.use_google_route_optimization = True
run_id = uuid.uuid4().hex[:12].upper()
prefix = f"HOMOLOGACAO_GOOGLE_FASE5_{run_id}"
email_prefix = prefix.lower()
created = {
    "org_id": None,
    "driver_id": None,
    "vehicle_id": None,
    "organization_address_id": None,
    "client_ids": [],
    "address_ids": [],
    "order_ids": [],
    "route_id": None,
}
homologation_success = False
cleanup_success = False
homologation_error = None


def cleanup_created_ids():
    try:
        with SessionLocal() as db:
            with db.begin():
                route = db.get(Rota, created["route_id"]) if created["route_id"] else None
                if route:
                    route.alternativa_recomendada_id = None
                    route.alternativa_escolhida_id = None
                    db.flush()
                    for position in db.query(RotaPosicao).filter(RotaPosicao.rota_id == route.id).all():
                        db.delete(position)
                    for history in db.query(RotaHistorico).filter(RotaHistorico.rota_id == route.id).all():
                        db.delete(history)
                    for route_entry in db.query(RotaEntrega).filter(RotaEntrega.rota_id == route.id).all():
                        db.delete(route_entry)
                    for alternative in db.query(RotaAlternativa).filter(RotaAlternativa.rota_id == route.id).all():
                        db.delete(alternative)
                    db.delete(route)

                order_ids = list(created["order_ids"])
                for delivery in db.query(Entrega).filter(Entrega.pedido_id.in_(order_ids)).all():
                    for item in db.query(HistoricoEntrega).filter(HistoricoEntrega.entrega_id == delivery.id).all():
                        db.delete(item)
                    for occurrence in db.query(Ocorrencia).filter(Ocorrencia.entrega_id == delivery.id).all():
                        db.delete(occurrence)
                    proof = db.query(ComprovanteEntrega).filter(ComprovanteEntrega.entrega_id == delivery.id).first()
                    if proof:
                        db.delete(proof)
                    db.delete(delivery)
                for order in db.query(Pedido).filter(Pedido.id.in_(order_ids)).all():
                    for item in db.query(PedidoItem).filter(PedidoItem.pedido_id == order.id).all():
                        db.delete(item)
                    db.delete(order)
                for address_id in created["address_ids"]:
                    address = db.get(Endereco, address_id)
                    if address:
                        db.delete(address)
                for client_id in created["client_ids"]:
                    client = db.get(Cliente, client_id)
                    if client:
                        db.delete(client)
                if created["organization_address_id"]:
                    address = db.get(Endereco, created["organization_address_id"])
                    if address:
                        organization = db.get(Organizacao, created["org_id"])
                        if organization and organization.endereco_id == address.id:
                            organization.endereco_id = None
                            db.flush()
                        db.delete(address)
                if created["vehicle_id"]:
                    vehicle = db.get(Veiculo, created["vehicle_id"])
                    if vehicle:
                        db.delete(vehicle)
                if created["driver_id"]:
                    driver = db.get(Usuario, created["driver_id"])
                    if driver:
                        db.delete(driver)
                if created["org_id"]:
                    organization = db.get(Organizacao, created["org_id"])
                    if organization:
                        db.delete(organization)
        return True
    except Exception as error:
        print(f"CLEANUP_ERROR={error}")
        return False


try:
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "admin@sistema.com", "senha": "123456"})
        assert login.status_code == 200, login.text
        admin_headers = {"Authorization": f"Bearer {login.json()['token']}"}

        org = client.post("/api/organizacoes", headers=admin_headers, json={
            "nome": f"{prefix} Organização",
            "cnpj": str(uuid.uuid4().int)[:14],
            "email": f"{email_prefix}@example.com",
            "telefone": "11999990001",
            "endereco": f"{prefix} endereço principal",
            "ativo": True,
        })
        assert org.status_code == 201, org.text
        created["org_id"] = org.json()["id"]

        address = client.post(f"/api/organizacoes/{created['org_id']}/enderecos", headers=admin_headers, json={
            "logradouro": f"Rua {prefix}", "numero": "500", "complemento": "Sala 1",
            "bairro": "Centro", "cidade": "São Paulo", "estado": "SP", "cep": "01000000",
            "tipo": "ORIGEM", "latitude": -23.550520, "longitude": -46.633308,
            "endereco_formatado": f"Rua {prefix}, 500 - Centro, São Paulo - SP", "principal": True,
        })
        assert address.status_code == 201, address.text
        created["organization_address_id"] = address.json()["id"]
        updated = client.put(f"/api/organizacoes/{created['org_id']}", headers=admin_headers, json={
            "nome": f"{prefix} Organização",
            "cnpj": org.json()["cnpj"],
            "email": f"{email_prefix}@example.com",
            "telefone": "11999990001",
            "endereco": f"{prefix} endereço principal",
            "ativo": True,
            "endereco_id": created["organization_address_id"],
        })
        assert updated.status_code == 200, updated.text

        driver = client.post("/api/usuarios", headers=admin_headers, json={
            "nome": f"{prefix} Motorista", "email": f"{email_prefix}-motorista@example.com",
            "senha": "123456", "perfil": "MOTORISTA", "organizacao_id": created["org_id"],
            "telefone": "11999990002",
        })
        assert driver.status_code == 201, driver.text
        created["driver_id"] = driver.json()["id"]

        vehicle = client.post("/api/veiculos", headers=admin_headers, json={
            "placa": f"H5G{uuid.uuid4().hex[:4].upper()}", "modelo": f"{prefix} Fiat Scudo",
            "marca": "Fiat", "ano": 2024, "cor": "Branco", "capacidade_carga": 1200,
            "capacidade_volume": 12, "tipo": "VAN", "status": "DISPONIVEL",
            "organizacao_id": created["org_id"], "motorista_id": created["driver_id"], "ativo": True,
        })
        assert vehicle.status_code == 201, vehicle.text
        created["vehicle_id"] = vehicle.json()["id"]

        product_id = client.get("/api/produtos", headers=admin_headers).json()[0]["id"]
        for index in range(1, 5):
            client_record = client.post("/api/clientes", headers=admin_headers, json={
                "nome": f"{prefix} Cliente {index}", "cpf_cnpj": str(uuid.uuid4().int)[:11],
                "email": f"{email_prefix}-cliente{index}@example.com", "telefone": f"119999900{index}",
            })
            assert client_record.status_code == 201, client_record.text
            client_id = client_record.json()["id"]
            created["client_ids"].append(client_id)
            end = client.post(f"/api/clientes/{client_id}/enderecos", headers=admin_headers, json={
                "logradouro": f"Rua {prefix} Entrega {index}", "numero": str(200 + index),
                "bairro": "Jardim Teste", "cidade": "São Paulo", "estado": "SP",
                "cep": f"010000{index:02d}", "tipo": "DESTINO", "latitude": -23.55 - index * 0.003,
                "longitude": -46.63 + index * 0.003,
                "endereco_formatado": f"Rua {prefix} Entrega {index}, {200 + index} - Jardim Teste, São Paulo - SP",
            })
            assert end.status_code == 201, end.text
            address_id = end.json()["id"]
            created["address_ids"].append(address_id)
            order = client.post("/api/pedidos", headers=admin_headers, json={
                "cliente_id": client_id, "organizacao_id": created["org_id"],
                "endereco_entrega_id": address_id, "prioridade": "NORMAL",
                "forma_pagamento": "DINHEIRO", "observacoes": f"{prefix} pedido {index}",
                "itens": [{"produto_id": product_id, "quantidade": 1, "valor_unitario": 10.0,
                           "observacoes": f"{prefix} item {index}"}],
            })
            assert order.status_code == 201, order.text
            created["order_ids"].append(order.json()["id"])

        driver_login = client.post("/api/auth/login", json={
            "email": f"{email_prefix}-motorista@example.com", "senha": "123456",
        })
        assert driver_login.status_code == 200, driver_login.text
        driver_headers = {"Authorization": f"Bearer {driver_login.json()['token']}"}
        response = client.post("/api/rotas/gerar", headers=admin_headers, json={
            "nome": f"{prefix} Rota", "descricao": f"{prefix} validacao end to end",
            "organizacao_id": created["org_id"], "veiculo_id": created["vehicle_id"],
            "motorista_id": created["driver_id"], "status": "PLANEJADA",
            "pedido_ids": created["order_ids"], "pontos_coleta_ids": [created["org_id"]],
        })
        assert response.status_code == 201, response.text
        route = response.json()
        created["route_id"] = route["id"]
        before = route_state(route)
        assert before["selected_id"] is None, before
        assert before["can_start"] is False, before
        assert before["distance"] == 0 and before["duration"] == 0, before
        assert before["official_delivery_sequence"] == [], before
        print("OFFICIAL_ROUTE_UNCHANGED_BEFORE_SELECTION=True")
        print(f"ALTERNATIVE_SELECTED_BEFORE_SELECTION={before['selected_id']}")
        print(f"CAN_START_BEFORE_SELECTION={before['can_start']}")
        print(f"OFFICIAL_ORDER_BEFORE_SELECTION={before['provisional_order']}")
        print(f"OFFICIAL_DISTANCE_BEFORE_SELECTION={before['distance']}")
        print(f"OFFICIAL_DURATION_BEFORE_SELECTION={before['duration']}")
        print(f"OFFICIAL_GEOMETRY_BEFORE_SELECTION={bool(before['geometry'])}")
        alternatives = route["alternativas"]
        assert len(alternatives) == 2, route
        assert {item["criterio"] for item in alternatives} == {"MAIS_CURTA", "MAIS_RAPIDA"}, route
        shortest = next(item for item in alternatives if item["criterio"] == "MAIS_CURTA")
        fastest = next(item for item in alternatives if item["criterio"] == "MAIS_RAPIDA")
        for alternative in alternatives:
            print(f"ALTERNATIVE={alternative['criterio']}")
            print(f"ALTERNATIVE_ID={alternative['id']}")
            print("ALTERNATIVE_PROVIDER=GOOGLE")
            print("ALTERNATIVE_OPTIMIZED=True")
            print(f"ALTERNATIVE_ORDER={alternative['sequencia']}")
            print(f"ALTERNATIVE_DISTANCE_KM={alternative['distancia_prevista']}")
            print(f"ALTERNATIVE_DURATION_HOURS={alternative['duracao_prevista']}")
            print(f"ALTERNATIVE_HAS_GEOMETRY={bool(alternative['route_geometry'])}")
        selected = client.post(f"/api/rotas/{created['route_id']}/selecionar-alternativa", headers=driver_headers, json={"alternativa_id": shortest["id"]})
        assert selected.status_code == 200, selected.text
        after = selected.json()
        after_state = route_state(after)
        assert after_state["selected_id"] == shortest["id"], after
        assert after_state["can_start"] is True, after
        assert after_state["official_delivery_sequence"] == shortest["sequencia"], after_state
        assert after_state["distance"] == shortest["distancia_prevista"], after_state
        assert after_state["duration"] == shortest["duracao_prevista"], after_state
        assert after_state["geometry"] == shortest["route_geometry"], after_state
        assert after.get("alternativa_escolhida_por") == created["driver_id"], after
        assert after.get("alternativa_escolhida_em"), after
        print(f"DRIVER_SELECTION_SUCCESS=True")
        print(f"SELECTED_ALTERNATIVE_ID={after_state['selected_id']}")
        print("SELECTED_CRITERION=MAIS_CURTA")
        print(f"SELECTION_USER_RECORDED={after.get('alternativa_escolhida_por') is not None}")
        print(f"SELECTION_TIMESTAMP_RECORDED={after.get('alternativa_escolhida_em') is not None}")
        print(f"OFFICIAL_ORDER_AFTER_SELECTION={after_state['official_order']}")
        print(f"ROTA_ENTREGA_ORDER_AFTER_SELECTION={after_state['official_delivery_sequence']}")
        print(f"OFFICIAL_DISTANCE_AFTER_SELECTION={after_state['distance']}")
        print(f"OFFICIAL_DURATION_AFTER_SELECTION={after_state['duration']}")
        print(f"OFFICIAL_GEOMETRY_AFTER_SELECTION={bool(after_state['geometry'])}")
        print(f"CAN_START_AFTER_SELECTION={after_state['can_start']}")
        repeated = client.post(f"/api/rotas/{created['route_id']}/selecionar-alternativa", headers=driver_headers, json={"alternativa_id": shortest["id"]})
        assert repeated.status_code == 200, repeated.text
        assert route_state(repeated.json()) == after_state, repeated.json()
        print("SAME_SELECTION_IDEMPOTENT=True")
        print(f"SAME_SELECTION_HTTP_STATUS={repeated.status_code}")
        changed = client.post(f"/api/rotas/{created['route_id']}/selecionar-alternativa", headers=driver_headers, json={"alternativa_id": fastest["id"]})
        assert changed.status_code == 422, changed.text
        rejected_state = route_state(client.get(f"/api/rotas/{created['route_id']}", headers=admin_headers).json())
        assert rejected_state == after_state, rejected_state
        print("CHANGE_SELECTION_REJECTED=True")
        print(f"CHANGE_SELECTION_HTTP_STATUS={changed.status_code}")
        print("ORIGINAL_SELECTION_PRESERVED_AFTER_REJECTED_CHANGE=True")
        homologation_success = True
except BaseException as error:
    homologation_error = error
    print(f"HOMOLOGATION_ERROR={error}")
finally:
    cleanup_success = cleanup_created_ids()
    print(f"RUN_ID={run_id}")
    print(f"HOMOLOGATION_SUCCESS={homologation_success}")
    print(f"CLEANUP_SUCCESS={cleanup_success}")

if homologation_error and not cleanup_success:
    raise RuntimeError("HOMOLOGATION_SUCCESS=false e CLEANUP_SUCCESS=false") from homologation_error
if homologation_error:
    raise homologation_error
if not homologation_success:
    raise RuntimeError("HOMOLOGATION_SUCCESS=false; falha preservada após cleanup")
if not cleanup_success:
    raise RuntimeError("CLEANUP_SUCCESS=false; cleanup falhou após homologação")

print("FINAL_VALIDATION=OK")
