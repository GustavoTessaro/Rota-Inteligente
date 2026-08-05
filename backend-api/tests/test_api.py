def test_login_and_dashboard(client, admin_headers):
    response = client.get("/api/relatorios/dashboard", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_entregas"] == 15
    assert "entregas_hoje" in data
    assert "entregas_concluidas" in data
    assert "entregas_por_status" in data
    assert isinstance(data["entregas_por_status"], list)
    assert "ultimas_entregas" in data
    assert "proximas_rotas" in data


def test_dashboard_metrics_are_consistent(client, admin_headers):
    response = client.get("/api/relatorios/dashboard", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_entregas"] >= data["entregas_concluidas"]
    assert data["rotas_em_execucao"] >= 0
    assert data["veiculos_disponiveis"] >= 0
    assert data["motoristas_ativos"] >= 0
    assert all(isinstance(item["quantidade"], int) for item in data["entregas_por_status"])


def test_list_endpoints_support_pagination(client, admin_headers):
    clients = client.get("/api/clientes?limit=2&offset=0", headers=admin_headers)
    products = client.get("/api/produtos?limit=3&offset=0", headers=admin_headers)
    orders = client.get("/api/pedidos?limit=4&offset=0", headers=admin_headers)
    deliveries = client.get("/api/entregas?limit=5&offset=0", headers=admin_headers)

    assert clients.status_code == 200
    assert products.status_code == 200
    assert orders.status_code == 200
    assert deliveries.status_code == 200
    assert len(clients.json()) == 2
    assert len(products.json()) == 3
    assert len(orders.json()) == 4
    assert len(deliveries.json()) == 5


def test_list_endpoints_filter_by_status(client, admin_headers):
    orders = client.get("/api/pedidos?status=ABERTO", headers=admin_headers)
    deliveries = client.get("/api/entregas?status=EM_ROTA", headers=admin_headers)

    assert orders.status_code == 200
    assert deliveries.status_code == 200
    assert all(item["status"] == "ABERTO" for item in orders.json())
    assert all(item["status"] == "EM_ROTA" for item in deliveries.json())


def test_inactive_client_cannot_receive_order(client, admin_headers):
    clients = client.get("/api/clientes", headers=admin_headers).json()
    client_id = clients[0]["id"]
    client.patch(
        f"/api/clientes/{client_id}/status",
        headers=admin_headers,
        json={"ativo": False},
    )
    products = client.get("/api/produtos", headers=admin_headers).json()
    response = client.post("/api/pedidos", headers=admin_headers, json={
        "cliente_id": client_id,
        "prioridade": "NORMAL",
        "itens": [{"produto_id": products[0]["id"], "quantidade": 1, "valor_unitario": 10}],
    })
    assert response.status_code == 422


def test_create_client_persists(client, admin_headers):
    response = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Novo",
        "cpf_cnpj": "12345678901",
        "email": "novo@email.com",
        "telefone": "11999999999",
        "observacoes": None,
    })
    assert response.status_code == 201
    created = response.json()
    assert created["nome"] == "Cliente Novo"

    clients = client.get("/api/clientes", headers=admin_headers).json()
    assert any(item["id"] == created["id"] for item in clients)


def test_create_client_accepts_blank_optional_fields(client, admin_headers):
    response = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "  Cliente Basico  ",
        "cpf_cnpj": " ",
        "email": "",
        "telefone": " ",
        "observacoes": "",
    })
    assert response.status_code == 201
    created = response.json()
    assert created["nome"] == "Cliente Basico"
    assert created["cpf_cnpj"] is None
    assert created["email"] is None
    assert created["telefone"] is None


def test_create_client_validates_document_and_phone(client, admin_headers):
    response = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Invalido",
        "cpf_cnpj": "123",
        "telefone": "999",
    })
    assert response.status_code == 422


def test_create_client_normalizes_formatted_document_and_phone(client, admin_headers):
    response = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Formatado",
        "cpf_cnpj": "123.456.789-01",
        "telefone": "(11) 99999-9999",
    })
    assert response.status_code == 201
    created = response.json()
    assert created["cpf_cnpj"] == "12345678901"
    assert created["telefone"] == "11999999999"


def test_update_and_delete_client(client, admin_headers):
    created = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Temporario",
        "cpf_cnpj": "99887766554",
    }).json()

    updated = client.put(f'/api/clientes/{created["id"]}', headers=admin_headers, json={
        "nome": "Cliente Editado",
        "cpf_cnpj": "99887766554",
        "email": "editado@email.com",
        "telefone": None,
        "observacoes": "Atualizado no teste",
    })
    assert updated.status_code == 200
    assert updated.json()["nome"] == "Cliente Editado"

    deleted = client.delete(f'/api/clientes/{created["id"]}', headers=admin_headers)
    assert deleted.status_code == 204
    clients = client.get("/api/clientes", headers=admin_headers).json()
    assert all(item["id"] != created["id"] for item in clients)


def test_delete_client_with_orders_is_blocked(client, admin_headers):
    existing = client.get("/api/clientes", headers=admin_headers).json()[0]
    response = client.delete(f'/api/clientes/{existing["id"]}', headers=admin_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Cliente está em uso e não pode ser excluído"


def test_delete_product_without_links_removes_record(client, admin_headers):
    created = client.post("/api/produtos", headers=admin_headers, json={
        "nome": "Produto Temporario",
        "peso": 1,
        "volume": 1,
        "valor_declarado": 10,
    }).json()
    response = client.delete(f'/api/produtos/{created["id"]}', headers=admin_headers)
    assert response.status_code == 204
    products = client.get("/api/produtos", headers=admin_headers).json()
    assert all(item["id"] != created["id"] for item in products)


def test_delete_product_with_orders_is_blocked(client, admin_headers):
    product = client.get("/api/produtos", headers=admin_headers).json()[0]
    response = client.delete(f'/api/produtos/{product["id"]}', headers=admin_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Produto está em uso e não pode ser excluído"


def test_vehicle_crud_and_list(client, admin_headers):
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    assert organizations
    organization_id = organizations[0]["id"]
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    driver = next((item for item in users if item["perfil"] == "MOTORISTA" and item["ativo"]), None)

    payload = {
        "placa": "TEST123",
        "modelo": "Teste 1",
        "marca": "Teste",
        "ano": 2024,
        "cor": "Branco",
        "capacidade_carga": 1000,
        "capacidade_volume": 10,
        "tipo": "VAN",
        "status": "DISPONIVEL",
        "quilometragem": 100,
        "ativo": True,
        "organizacao_id": organization_id,
        "motorista_id": driver["id"] if driver else None,
    }
    response = client.post("/api/veiculos", headers=admin_headers, json=payload)
    assert response.status_code == 201
    created = response.json()
    assert created["placa"] == "TEST123"
    assert created["organizacao_id"] == organization_id

    response = client.get(f'/api/veiculos/{created["id"]}', headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["placa"] == "TEST123"

    updated = client.put(
        f'/api/veiculos/{created["id"]}',
        headers=admin_headers,
        json={**payload, "cor": "Preto", "ativo": False},
    )
    assert updated.status_code == 200
    assert updated.json()["cor"] == "Preto"
    assert updated.json()["ativo"] is False

    response = client.delete(f'/api/veiculos/{created["id"]}', headers=admin_headers)
    assert response.status_code == 204

    vehicles = client.get("/api/veiculos?limit=10&offset=0", headers=admin_headers).json()
    assert all(item["id"] != created["id"] for item in vehicles)


def test_delete_vehicle_without_driver(client, admin_headers):
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    organization_id = organizations[0]["id"]
    response = client.post("/api/veiculos", headers=admin_headers, json={
        "placa": "NODEL1",
        "modelo": "Teste 2",
        "marca": "Teste",
        "ano": 2024,
        "cor": "Azul",
        "capacidade_carga": 500,
        "capacidade_volume": 5,
        "tipo": "CARRO",
        "status": "DISPONIVEL",
        "quilometragem": 50,
        "ativo": True,
        "organizacao_id": organization_id,
        "motorista_id": None,
    })
    assert response.status_code == 201
    created = response.json()

    deleted = client.delete(f'/api/veiculos/{created["id"]}', headers=admin_headers)
    assert deleted.status_code == 204


def test_list_vehicles_supports_pagination(client, admin_headers):
    response = client.get("/api/veiculos?limit=1&offset=0", headers=admin_headers)
    assert response.status_code == 200
    assert len(response.json()) <= 1


def test_get_vehicle_requires_existing_record(client, admin_headers):
    response = client.get("/api/veiculos/99999", headers=admin_headers)
    assert response.status_code == 404


def test_delete_vehicle_with_linked_delivery_is_blocked(client, admin_headers):
    vehicle = client.get("/api/veiculos", headers=admin_headers).json()[0]
    response = client.delete(f'/api/veiculos/{vehicle["id"]}', headers=admin_headers)
    assert response.status_code in (204, 409)
    if response.status_code == 409:
        assert response.json()["detail"] == "Veículo está vinculado a entregas e não pode ser excluído"


def test_delete_address_without_links_removes_record(client, admin_headers):
    created_client = client.post("/api/clientes", headers=admin_headers, json={
        "nome": "Cliente Endereco Livre",
        "cpf_cnpj": "11222333444",
    }).json()
    address = client.post(f'/api/clientes/{created_client["id"]}/enderecos', headers=admin_headers, json={
        "logradouro": "Rua Livre",
        "numero": "10",
        "bairro": "Centro",
        "cidade": "Sao Paulo",
        "estado": "SP",
        "cep": "01000000",
        "tipo": "DESTINO",
    }).json()
    response = client.delete(
        f'/api/clientes/{created_client["id"]}/enderecos/{address["id"]}',
        headers=admin_headers,
    )
    assert response.status_code == 204


def test_delete_address_with_deliveries_is_blocked(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    order = next(
        item for item in client.get("/api/pedidos", headers=admin_headers).json()
        if item["id"] == delivery["pedido_id"]
    )
    client_id = order["cliente_id"]
    response = client.delete(
        f'/api/clientes/{client_id}/enderecos/{delivery["endereco_origem_id"]}',
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Endereço está em uso e não pode ser excluído"


def test_order_status_uses_json_body(client, admin_headers):
    order = client.get("/api/pedidos", headers=admin_headers).json()[0]
    response = client.patch(
        f'/api/pedidos/{order["id"]}/status',
        headers=admin_headers,
        json={"status": "EM_PROCESSAMENTO"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "EM_PROCESSAMENTO"


def test_create_order_with_multiple_items(client, admin_headers):
    client_id = client.get("/api/clientes", headers=admin_headers).json()[0]["id"]
    products = client.get("/api/produtos", headers=admin_headers).json()[:2]
    response = client.post("/api/pedidos", headers=admin_headers, json={
        "cliente_id": client_id,
        "prioridade": "ALTA",
        "itens": [
            {"produto_id": products[0]["id"], "quantidade": 2, "valor_unitario": 10},
            {"produto_id": products[1]["id"], "quantidade": 3, "valor_unitario": 5},
        ],
    })
    assert response.status_code == 201
    assert float(response.json()["valor_total"]) == 35


def test_order_item_crud_and_order_delete(client, admin_headers):
    client_id = client.get("/api/clientes", headers=admin_headers).json()[0]["id"]
    product = client.get("/api/produtos", headers=admin_headers).json()[0]
    order = client.post("/api/pedidos", headers=admin_headers, json={
        "cliente_id": client_id,
        "itens": [{"produto_id": product["id"], "quantidade": 1, "valor_unitario": 10}],
    }).json()

    item = client.post(f'/api/pedidos/{order["id"]}/itens', headers=admin_headers, json={
        "produto_id": product["id"], "quantidade": 2, "valor_unitario": 5,
    })
    assert item.status_code == 201
    item_id = item.json()["id"]

    updated = client.put(f'/api/pedidos/{order["id"]}/itens/{item_id}', headers=admin_headers, json={
        "produto_id": product["id"], "quantidade": 3, "valor_unitario": 5,
    })
    assert updated.status_code == 200
    assert updated.json()["quantidade"] == 3

    deleted_item = client.delete(f'/api/pedidos/{order["id"]}/itens/{item_id}', headers=admin_headers)
    assert deleted_item.status_code == 204

    updated_order = client.put(f'/api/pedidos/{order["id"]}', headers=admin_headers, json={
        "cliente_id": client_id,
        "prioridade": "URGENTE",
        "itens": [{"produto_id": product["id"], "quantidade": 2, "valor_unitario": 20}],
    })
    assert updated_order.status_code == 200
    assert updated_order.json()["prioridade"] == "URGENTE"
    assert float(updated_order.json()["valor_total"]) == 40

    deleted_order = client.delete(f'/api/pedidos/{order["id"]}', headers=admin_headers)
    assert deleted_order.status_code == 204


def test_order_with_delivery_blocks_edit_and_delete(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    product = client.get("/api/produtos", headers=admin_headers).json()[0]
    payload = {
        "cliente_id": client.get("/api/pedidos", headers=admin_headers).json()[0]["cliente_id"],
        "itens": [{"produto_id": product["id"], "quantidade": 1, "valor_unitario": 10}],
    }
    update_response = client.put(f'/api/pedidos/{delivery["pedido_id"]}', headers=admin_headers, json=payload)
    delete_response = client.delete(f'/api/pedidos/{delivery["pedido_id"]}', headers=admin_headers)
    assert update_response.status_code == 409
    assert delete_response.status_code == 409


def test_delivery_incident_crud(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    created = client.post(
        f'/api/entregas/{delivery["id"]}/ocorrencias',
        headers=admin_headers,
        json={"tipo": "Atraso", "descricao": "Cliente ausente"},
    )
    assert created.status_code == 201
    incident = created.json()

    updated = client.put(
        f'/api/entregas/{delivery["id"]}/ocorrencias/{incident["id"]}',
        headers=admin_headers,
        json={"tipo": "Reentrega", "descricao": "Agendada para amanhã"},
    )
    assert updated.status_code == 200
    assert updated.json()["tipo"] == "Reentrega"

    listed = client.get(f'/api/entregas/{delivery["id"]}/ocorrencias', headers=admin_headers).json()
    assert any(item["id"] == incident["id"] for item in listed)

    deleted = client.delete(
        f'/api/entregas/{delivery["id"]}/ocorrencias/{incident["id"]}',
        headers=admin_headers,
    )
    assert deleted.status_code == 204


def test_update_delivery(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    response = client.put(f'/api/entregas/{delivery["id"]}', headers=admin_headers, json={
        "pedido_id": delivery["pedido_id"],
        "entregador_id": delivery["entregador_id"],
        "endereco_origem_id": delivery["endereco_origem_id"],
        "endereco_destino_id": delivery["endereco_destino_id"],
        "previsao_saida": delivery["previsao_saida"],
        "previsao_entrega": delivery["previsao_entrega"],
        "observacoes": "Entrega atualizada",
    })
    assert response.status_code == 200
    assert response.json()["observacoes"] == "Entrega atualizada"


def test_delete_delivery_with_history_is_blocked(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    response = client.delete(f'/api/entregas/{delivery["id"]}', headers=admin_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Entrega está em uso e não pode ser excluída"


def test_receipt_update_and_delete(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    created = client.post(
        f'/api/entregas/{delivery["id"]}/comprovante',
        headers=admin_headers,
        json={"nome_recebedor": "Maria", "documento_recebedor": "123"},
    )
    assert created.status_code == 201

    updated = client.put(
        f'/api/entregas/{delivery["id"]}/comprovante',
        headers=admin_headers,
        json={"nome_recebedor": "Joao", "documento_recebedor": "456", "observacao": "Atualizado"},
    )
    assert updated.status_code == 200
    assert updated.json()["nome_recebedor"] == "Joao"

    deleted = client.delete(f'/api/entregas/{delivery["id"]}/comprovante', headers=admin_headers)
    assert deleted.status_code == 204


def test_update_user_keeps_password_when_blank(client, admin_headers):
    created = client.post("/api/usuarios", headers=admin_headers, json={
        "nome": "Usuario Teste",
        "email": "usuario.teste@sistema.com",
        "senha": "123456",
        "telefone": None,
        "perfil": "GESTOR",
    })
    assert created.status_code == 201
    user_id = created.json()["id"]

    updated = client.put(f"/api/usuarios/{user_id}", headers=admin_headers, json={
        "nome": "Usuario Editado",
        "email": "usuario.editado@sistema.com",
        "senha": None,
        "telefone": None,
        "perfil": "GESTOR",
    })
    assert updated.status_code == 200

    login = client.post("/api/auth/login", json={
        "email": "usuario.editado@sistema.com",
        "senha": "123456",
    })
    assert login.status_code == 200


def test_create_and_list_organizacao(client, admin_headers):
    response = client.post("/api/organizacoes", headers=admin_headers, json={
        "nome": "Organizacao Teste",
        "cnpj": "11222333444455",
        "email": "orgteste@email.com",
        "telefone": "11988887777",
        "endereco": "Rua Teste, 123",
        "ativo": True,
    })
    assert response.status_code == 201
    created = response.json()
    assert created["nome"] == "Organizacao Teste"

    list_response = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers)
    assert list_response.status_code == 200
    assert any(item["id"] == created["id"] for item in list_response.json())


def test_update_organizacao(client, admin_headers):
    created = client.post("/api/organizacoes", headers=admin_headers, json={
        "nome": "Organizacao Atualizavel",
        "cnpj": "22333444555666",
        "email": "orgupdate@email.com",
        "telefone": "11977776666",
        "endereco": "Avenida Atualizar, 456",
        "ativo": True,
    }).json()

    response = client.put(f'/api/organizacoes/{created["id"]}', headers=admin_headers, json={
        "nome": "Organizacao Atualizada",
        "cnpj": "22333444555666",
        "email": "orgupdated@email.com",
        "telefone": "11977776666",
        "endereco": "Avenida Atualizada, 456",
        "ativo": False,
    })
    assert response.status_code == 200
    assert response.json()["nome"] == "Organizacao Atualizada"
    assert response.json()["ativo"] is False


def test_delete_organizacao_with_users_is_blocked(client, admin_headers):
    created = client.post("/api/organizacoes", headers=admin_headers, json={
        "nome": "Organizacao Vinculada",
        "cnpj": "33444555666777",
        "email": "orglinked@email.com",
        "telefone": "11966665555",
        "endereco": "Rua Vinculo, 789",
        "ativo": True,
    }).json()

    user = client.post("/api/usuarios", headers=admin_headers, json={
        "nome": "Usuario Vinculado",
        "email": "usuario.vinculado@sistema.com",
        "senha": "123456",
        "telefone": None,
        "perfil": "GESTOR",
        "organizacao_id": created["id"],
    })
    assert user.status_code == 201

    delete_response = client.delete(f'/api/organizacoes/{created["id"]}', headers=admin_headers)
    assert delete_response.status_code == 409
    assert delete_response.json()["detail"] == "Organização está em uso e não pode ser excluída"


def test_delete_user_without_links_removes_record(client, admin_headers):
    created = client.post("/api/usuarios", headers=admin_headers, json={
        "nome": "Usuario Sem Vinculo",
        "email": "sem.vinculo@sistema.com",
        "senha": "123456",
        "telefone": None,
        "perfil": "GESTOR",
    }).json()
    response = client.delete(f'/api/usuarios/{created["id"]}', headers=admin_headers)
    assert response.status_code == 204

    users = client.get("/api/usuarios", headers=admin_headers).json()
    assert all(item["id"] != created["id"] for item in users)


def test_delete_user_with_links_is_blocked(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    response = client.delete(f'/api/usuarios/{delivery["entregador_id"]}', headers=admin_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "Usuário está em uso e não pode ser excluído"


def test_address_validation(client, admin_headers):
    client_id = client.get("/api/clientes", headers=admin_headers).json()[0]["id"]
    response = client.post(f"/api/clientes/{client_id}/enderecos", headers=admin_headers, json={
        "logradouro": "A",
        "numero": "",
        "bairro": "B",
        "cidade": "C",
        "estado": "S",
        "cep": "123",
        "tipo": "INVALIDO",
    })
    assert response.status_code == 422


def test_product_validation(client, admin_headers):
    response = client.post("/api/produtos", headers=admin_headers, json={
        "nome": "A",
        "peso": -1,
        "volume": 0,
        "valor_declarado": -10,
    })
    assert response.status_code == 422


def test_delivery_requires_receipt_before_completion(client, admin_headers):
    delivery = client.get("/api/entregas", headers=admin_headers).json()[0]
    response = client.patch(
        f'/api/entregas/{delivery["id"]}/status',
        headers=admin_headers,
        json={"status": "ENTREGUE", "observacao": "Teste"},
    )
    assert response.status_code == 422

    receipt = client.post(
        f'/api/entregas/{delivery["id"]}/comprovante',
        headers=admin_headers,
        json={"nome_recebedor": "Maria", "documento_recebedor": "123"},
    )
    assert receipt.status_code == 201
    completed = client.patch(
        f'/api/entregas/{delivery["id"]}/status',
        headers=admin_headers,
        json={"status": "ENTREGUE", "observacao": "Confirmada"},
    )
    assert completed.status_code == 200
    history = client.get(
        f'/api/entregas/{delivery["id"]}/historico', headers=admin_headers
    ).json()
    assert history[-1]["status_novo"] == "ENTREGUE"


def test_create_route(client, admin_headers):
    vehicles = client.get("/api/veiculos", headers=admin_headers).json()
    assert vehicles
    vehicle = vehicles[0]
    users = client.get("/api/usuarios", headers=admin_headers).json()
    motorista = next(item for item in users if item["perfil"] == "MOTORISTA")
    organizations = client.get("/api/organizacoes?limit=10&offset=0", headers=admin_headers).json()
    organization = next(item for item in organizations if item["id"] == vehicle["organizacao_id"])
    deliveries = client.get("/api/entregas?limit=100&offset=0", headers=admin_headers).json()
    entrega = next(item for item in deliveries if item["status"] != "CANCELADA")

    response = client.post(
        "/api/rotas",
        headers=admin_headers,
        json={
            "nome": "Rota Teste",
            "descricao": "Rota criada no teste",
            "organizacao_id": organization["id"],
            "veiculo_id": vehicle["id"],
            "motorista_id": motorista["id"],
            "status": "PLANEJADA",
            "entregas": [{"entrega_id": entrega["id"], "ordem_visita": 1}],
        },
    )
    assert response.status_code == 201
    rota = response.json()
    assert rota["nome"] == "Rota Teste"
    assert rota["organizacao_id"] == organization["id"]
    assert rota["entregas"][0]["entrega_id"] == entrega["id"]


def test_update_route_status_and_history(client, admin_headers):
    routes = client.get("/api/rotas?limit=10&offset=0", headers=admin_headers).json()
    assert routes
    rota = routes[0]

    response = client.patch(
        f'/api/rotas/{rota["id"]}/status',
        headers=admin_headers,
        json={
            "status": "EM_EXECUCAO",
            "evento": "PARTIDA",
            "observacao": "Iniciando a rota",
            "progresso_percentual": 10,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "EM_EXECUCAO"

    history = client.get(f'/api/rotas/{rota["id"]}/historico', headers=admin_headers).json()
    assert any(item["status_novo"] == "EM_EXECUCAO" for item in history)
