def test_create_order_with_delivery_address(client, admin_headers):
    organization = client.get("/api/organizacoes", headers=admin_headers).json()[0]
    customer = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Entrega",
        "cpf_cnpj": "11122233344",
    }).json()
    address = client.post(f'/api/clientes/{customer["id"]}/enderecos', headers=admin_headers, json={
        "logradouro": "Rua da Entrega",
        "numero": "100",
        "bairro": "Centro",
        "cidade": "São Paulo",
        "estado": "SP",
        "cep": "01000000",
        "tipo": "DESTINO",
    }).json()
    product = client.get("/api/produtos", headers=admin_headers).json()[0]

    response = client.post("/api/pedidos", headers=admin_headers, json={
        "cliente_id": customer["id"],
        "organizacao_id": organization["id"],
        "prioridade": "ALTA",
        "forma_pagamento": "PIX",
        "observacoes": "Entrega prioritária",
        "endereco_entrega_id": address["id"],
        "itens": [
            {"produto_id": product["id"], "quantidade": 2, "valor_unitario": 15.5},
        ],
    })

    assert response.status_code == 201
    payload = response.json()
    assert payload["cliente_id"] == customer["id"]
    assert payload["endereco_entrega_id"] == address["id"]


def test_generate_route_from_selected_orders_and_collection_points(client, admin_headers):
    customer_1 = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Um",
        "cpf_cnpj": "44455566677",
    }).json()
    customer_2 = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Dois",
        "cpf_cnpj": "77788899900",
    }).json()

    addr_1 = client.post(f'/api/clientes/{customer_1["id"]}/enderecos', headers=admin_headers, json={
        "logradouro": "Rua A",
        "numero": "11",
        "bairro": "Centro",
        "cidade": "São Paulo",
        "estado": "SP",
        "cep": "01001000",
        "tipo": "DESTINO",
    }).json()
    addr_2 = client.post(f'/api/clientes/{customer_2["id"]}/enderecos', headers=admin_headers, json={
        "logradouro": "Rua B",
        "numero": "22",
        "bairro": "Centro",
        "cidade": "São Paulo",
        "estado": "SP",
        "cep": "01002000",
        "tipo": "DESTINO",
    }).json()
    product = client.get("/api/produtos", headers=admin_headers).json()[0]
    organization = client.get("/api/organizacoes", headers=admin_headers).json()[0]

    order_1 = client.post("/api/pedidos", headers=admin_headers, json={
        "cliente_id": customer_1["id"],
        "organizacao_id": organization["id"],
        "endereco_entrega_id": addr_1["id"],
        "itens": [{"produto_id": product["id"], "quantidade": 1, "valor_unitario": 10}],
    }).json()
    order_2 = client.post("/api/pedidos", headers=admin_headers, json={
        "cliente_id": customer_2["id"],
        "organizacao_id": organization["id"],
        "endereco_entrega_id": addr_2["id"],
        "itens": [{"produto_id": product["id"], "quantidade": 2, "valor_unitario": 20}],
    }).json()

    organization = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()[0]
    vehicle = client.get("/api/veiculos?limit=10&offset=0", headers=admin_headers).json()[0]
    driver = next(item for item in client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json() if item["perfil"] == "MOTORISTA")

    response = client.post("/api/rotas/gerar", headers=admin_headers, json={
        "nome": "Operação de entrega",
        "descricao": "Rota gerada a partir de pedidos",
        "organizacao_id": organization["id"],
        "veiculo_id": vehicle["id"],
        "motorista_id": driver["id"],
        "pedido_ids": [order_1["id"], order_2["id"]],
        "pontos_coleta_ids": [organization["id"]],
        "status": "OTIMIZANDO",
    })

    assert response.status_code == 201
    payload = response.json()
    assert payload["organizacao_id"] == organization["id"]
    assert payload["motorista_id"] == driver["id"]
    assert payload["veiculo_id"] == vehicle["id"]
    assert payload["status"] == "PRONTA"
    assert len(payload["entregas"]) == 2


def test_assign_driver_and_vehicle_for_generated_route(client, admin_headers):
    organization = client.get("/api/organizacoes", headers=admin_headers).json()[0]
    customer = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Rota",
        "cpf_cnpj": "12345678909",
    }).json()
    address = client.post(f'/api/clientes/{customer["id"]}/enderecos', headers=admin_headers, json={
        "logradouro": "Praça da Rota",
        "numero": "7",
        "bairro": "Centro",
        "cidade": "São Paulo",
        "estado": "SP",
        "cep": "01003000",
        "tipo": "DESTINO",
    }).json()
    product = client.get("/api/produtos", headers=admin_headers).json()[0]
    order = client.post("/api/pedidos", headers=admin_headers, json={
        "cliente_id": customer["id"],
        "organizacao_id": organization["id"],
        "endereco_entrega_id": address["id"],
        "itens": [{"produto_id": product["id"], "quantidade": 1, "valor_unitario": 8}],
    }).json()

    organization = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()[0]
    vehicle = client.get("/api/veiculos?limit=10&offset=0", headers=admin_headers).json()[0]
    driver = next(item for item in client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json() if item["perfil"] == "MOTORISTA")

    generated = client.post("/api/rotas/gerar", headers=admin_headers, json={
        "nome": "Rota com motorista",
        "organizacao_id": organization["id"],
        "veiculo_id": vehicle["id"],
        "motorista_id": driver["id"],
        "pedido_ids": [order["id"]],
        "pontos_coleta_ids": [organization["id"]],
    }).json()

    updated = client.patch(f'/api/rotas/{generated["id"]}/status', headers=admin_headers, json={
        "status": "AGUARDANDO_ACEITE",
        "evento": "PARTIDA",
        "observacao": "Rota pronta para aceite do motorista",
    })

    assert updated.status_code == 200
    assert updated.json()["motorista_id"] == driver["id"]
    assert updated.json()["veiculo_id"] == vehicle["id"]
    assert updated.json()["status"] == "AGUARDANDO_ACEITE"
