import os

os.environ["DATABASE_URL"] = "sqlite:///./test_entregas.db"
os.environ["SEED_DATABASE"] = "true"

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import Rota
from app.services.google_maps_service import GoogleMapsService

client = TestClient(app)
login = client.post("/api/auth/login", json={"email": "admin@sistema.com", "senha": "123456"})
headers = {"Authorization": f"Bearer {login.json()['token']}"}

customer = client.post("/api/clientes", headers=headers, json={"nome": "Cliente Audit", "cpf_cnpj": "11122233344"}).json()
address = client.post(
    f"/api/clientes/{customer['id']}/enderecos",
    headers=headers,
    json={
        "logradouro": "Rua da Auditoria",
        "numero": "123",
        "bairro": "Centro",
        "cidade": "São Paulo",
        "estado": "SP",
        "cep": "01000000",
        "tipo": "DESTINO",
        "complemento": "Casa",
    },
).json()
print("address_created=", address)

product = client.get("/api/produtos", headers=headers).json()[0]
order = client.post(
    "/api/pedidos",
    headers=headers,
    json={
        "cliente_id": customer["id"],
        "endereco_entrega_id": address["id"],
        "itens": [{"produto_id": product["id"], "quantidade": 1, "valor_unitario": 15}],
    },
).json()
print("order_created=", order)

org = client.get("/api/organizacoes?limit=10&offset=0", headers=headers).json()[0]
vehicle = client.get("/api/veiculos", headers=headers).json()[0]
driver = next(item for item in client.get("/api/usuarios", headers=headers).json() if item["perfil"] == "MOTORISTA" and item["ativo"])

payload = {
    "nome": "Rota demo",
    "descricao": "audit",
    "organizacao_id": org["id"],
    "veiculo_id": vehicle["id"],
    "motorista_id": driver["id"],
    "pedido_ids": [order["id"]],
    "pontos_coleta_ids": [org["id"]],
    "status": "OTIMIZANDO",
}
route_response = client.post("/api/rotas/gerar", headers=headers, json=payload)
print("route_response_status=", route_response.status_code)
print("route_response_json=", route_response.json())

service_response = GoogleMapsService().optimize_route(
    origin={"lat": -23.55, "lng": -46.63},
    destination={"lat": -23.56, "lng": -46.64},
    waypoints=[{"lat": -23.57, "lng": -46.65}],
)
print("default_service_optimization=", service_response)

with SessionLocal() as db:
    saved = db.get(Rota, route_response.json()["id"])
    print("saved_status=", saved.status)
    print("saved_distancia_prevista=", saved.distancia_prevista)
    print("saved_duracao_prevista=", saved.duracao_prevista)
    print("saved_route_geometry=", saved.route_geometry)
    print("saved_google_route_id=", saved.google_route_id)
    print("saved_google_optimization_request_id=", saved.google_optimization_request_id)
