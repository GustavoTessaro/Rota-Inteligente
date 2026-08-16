"""
Test Etapa 2: Pedido integration with Organização (organizacao_id).
Tests that orders can be created and persisted with an associated organization.
"""
import pytest
from app.models import Usuario, Organizacao, Cliente, Endereco, Pedido, Produto, PedidoItem


def test_create_pedido_with_organizacao_id(client, admin_headers):
    """Test creating an order with organizacao_id."""
    # Get existing organizations
    orgs_response = client.get("/api/organizacoes?limit=100&offset=0", headers=admin_headers)
    organizations = orgs_response.json()
    assert len(organizations) > 0
    org_id = organizations[0]["id"]

    # Get existing clients
    clients_response = client.get("/api/clientes", headers=admin_headers)
    clients = clients_response.json()
    assert len(clients) > 0
    cliente_id = clients[0]["id"]

    # Get client addresses
    addresses_response = client.get(f"/api/clientes/{cliente_id}/enderecos", headers=admin_headers)
    addresses = addresses_response.json()
    assert len(addresses) > 0
    address_id = addresses[0]["id"]

    # Get existing products
    products_response = client.get("/api/produtos", headers=admin_headers)
    products = products_response.json()
    assert len(products) > 0
    produto_id = products[0]["id"]

    # Create order with organizacao_id
    response = client.post(
        "/api/pedidos",
        headers=admin_headers,
        json={
            "cliente_id": cliente_id,
            "organizacao_id": org_id,
            "endereco_entrega_id": address_id,
            "prioridade": "NORMAL",
            "itens": [
                {
                    "produto_id": produto_id,
                    "quantidade": 1,
                    "valor_unitario": 100.0,
                }
            ],
        },
    )

    assert response.status_code in [200, 201]
    data = response.json()
    assert data["organizacao_id"] == org_id
    assert data["cliente_id"] == cliente_id


def test_create_pedido_without_organizacao_id(client, admin_headers):
    """New orders must select an organization; NULL remains only for legacy records."""
    # Get existing clients
    clients_response = client.get("/api/clientes", headers=admin_headers)
    clients = clients_response.json()
    assert len(clients) > 0
    cliente_id = clients[0]["id"]

    # Get client addresses
    addresses_response = client.get(f"/api/clientes/{cliente_id}/enderecos", headers=admin_headers)
    addresses = addresses_response.json()
    assert len(addresses) > 0
    address_id = addresses[0]["id"]

    # Get existing products
    products_response = client.get("/api/produtos", headers=admin_headers)
    products = products_response.json()
    assert len(products) > 0
    produto_id = products[0]["id"]

    response = client.post(
        "/api/pedidos",
        headers=admin_headers,
        json={
            "cliente_id": cliente_id,
            "endereco_entrega_id": address_id,
            "prioridade": "NORMAL",
            "itens": [
                {
                    "produto_id": produto_id,
                    "quantidade": 2,
                    "valor_unitario": 50.0,
                }
            ],
        },
    )

    assert response.status_code in [400, 422]


def test_update_pedido_with_organizacao_id(client, admin_headers):
    """Test updating an order to add organizacao_id."""
    # Get existing organizations
    orgs_response = client.get("/api/organizacoes?limit=100&offset=0", headers=admin_headers)
    organizations = orgs_response.json()
    assert len(organizations) > 0
    org_id = organizations[0]["id"]

    # Get existing clients
    clients_response = client.get("/api/clientes", headers=admin_headers)
    clients = clients_response.json()
    assert len(clients) > 0
    cliente_id = clients[0]["id"]

    # Get client addresses
    addresses_response = client.get(f"/api/clientes/{cliente_id}/enderecos", headers=admin_headers)
    addresses = addresses_response.json()
    assert len(addresses) > 0
    address_id = addresses[0]["id"]

    # Get existing products
    products_response = client.get("/api/produtos", headers=admin_headers)
    products = products_response.json()
    assert len(products) > 0
    produto_id = products[0]["id"]

    # Create order with organization from the beginning (new orders must define it)
    create_response = client.post(
        "/api/pedidos",
        headers=admin_headers,
        json={
            "cliente_id": cliente_id,
            "organizacao_id": org_id,
            "endereco_entrega_id": address_id,
            "prioridade": "ALTA",
            "itens": [
                {
                    "produto_id": produto_id,
                    "quantidade": 1,
                    "valor_unitario": 200.0,
                }
            ],
        },
    )
    assert create_response.status_code in [200, 201]
    pedido_id = create_response.json()["id"]

    # Update order with organizacao_id kept valid
    update_response = client.put(
        f"/api/pedidos/{pedido_id}",
        headers=admin_headers,
        json={
            "cliente_id": cliente_id,
            "organizacao_id": org_id,
            "endereco_entrega_id": address_id,
            "prioridade": "ALTA",
            "itens": [
                {
                    "produto_id": produto_id,
                    "quantidade": 1,
                    "valor_unitario": 200.0,
                }
            ],
        },
    )

    assert update_response.status_code in [200, 201]
    data = update_response.json()
    assert data["organizacao_id"] == org_id


def test_invalid_organizacao_id(client, admin_headers):
    """Test creating an order with non-existent organizacao_id."""
    # Get existing clients
    clients_response = client.get("/api/clientes", headers=admin_headers)
    clients = clients_response.json()
    assert len(clients) > 0
    cliente_id = clients[0]["id"]

    # Get client addresses
    addresses_response = client.get(f"/api/clientes/{cliente_id}/enderecos", headers=admin_headers)
    addresses = addresses_response.json()
    assert len(addresses) > 0
    address_id = addresses[0]["id"]

    # Get existing products
    products_response = client.get("/api/produtos", headers=admin_headers)
    products = products_response.json()
    assert len(products) > 0
    produto_id = products[0]["id"]

    # Try to create order with invalid organizacao_id
    response = client.post(
        "/api/pedidos",
        headers=admin_headers,
        json={
            "cliente_id": cliente_id,
            "organizacao_id": 99999,  # Non-existent ID
            "endereco_entrega_id": address_id,
            "prioridade": "NORMAL",
            "itens": [
                {
                    "produto_id": produto_id,
                    "quantidade": 1,
                    "valor_unitario": 10.0,
                }
            ],
        },
    )

    # Should reject with validation error
    assert response.status_code == 400 or response.status_code == 404

