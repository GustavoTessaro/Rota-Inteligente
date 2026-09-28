OPERATOR_EMAIL = "admin@sistema.com"
OPERATOR_PASSWORD = "123456"
TARGET_PASSWORD = "target-admin-password"


def _current_operator(client, admin_headers):
    response = client.get("/api/auth/me", headers=admin_headers)
    assert response.status_code == 200
    operator = response.json()
    assert operator["email"] == OPERATOR_EMAIL
    assert operator["perfil"] == "ADMIN"
    login = client.post(
        "/api/auth/login",
        json={"email": OPERATOR_EMAIL, "senha": OPERATOR_PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["usuario"]["id"] == operator["id"]
    return operator


def _create_admin_target(client, admin_headers, email="target.admin@sistema.com"):
    response = client.post(
        "/api/usuarios",
        headers=admin_headers,
        json={
            "nome": "Admin Alvo",
            "email": email,
            "senha": TARGET_PASSWORD,
            "telefone": None,
            "perfil": "ADMIN",
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_non_admin_target(client, admin_headers, email="target.manager@sistema.com"):
    response = client.post(
        "/api/usuarios",
        headers=admin_headers,
        json={
            "nome": "Gestor Alvo",
            "email": email,
            "senha": TARGET_PASSWORD,
            "telefone": None,
            "perfil": "GESTOR",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_delete_only_admin_is_rejected(client, admin_headers):
    operator = _current_operator(client, admin_headers)

    response = client.request(
        "DELETE",
        f"/api/usuarios/{operator['id']}",
        headers=admin_headers,
        json={"senha": OPERATOR_PASSWORD},
    )

    assert response.status_code >= 400
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    assert any(user["id"] == operator["id"] for user in users)


def test_deactivate_only_admin_is_rejected(client, admin_headers):
    operator = _current_operator(client, admin_headers)

    response = client.patch(
        f"/api/usuarios/{operator['id']}/status",
        headers=admin_headers,
        json={"ativo": False, "senha": "incorrect-operator-password"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Não é possível desativar o único ADMIN cadastrado. "
        "Cadastre outro ADMIN antes de realizar esta operação."
    )


def test_delete_admin_with_wrong_operator_password_is_rejected(client, admin_headers):
    operator = _current_operator(client, admin_headers)
    target = _create_admin_target(client, admin_headers)
    assert target["id"] != operator["id"]
    assert TARGET_PASSWORD != OPERATOR_PASSWORD

    response = client.request(
        "DELETE",
        f"/api/usuarios/{target['id']}",
        headers=admin_headers,
        json={"senha": "incorrect-operator-password"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Senha do usuário autenticado inválida"
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    assert any(user["id"] == target["id"] for user in users)


def test_deactivate_admin_with_wrong_operator_password_is_rejected(client, admin_headers):
    operator = _current_operator(client, admin_headers)
    target = _create_admin_target(client, admin_headers)
    assert target["id"] != operator["id"]
    assert TARGET_PASSWORD != OPERATOR_PASSWORD

    response = client.patch(
        f"/api/usuarios/{target['id']}/status",
        headers=admin_headers,
        json={"ativo": False, "senha": "incorrect-operator-password"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Senha do usuário autenticado inválida"
    users = client.get("/api/usuarios?limit=100&offset=0", headers=admin_headers).json()
    target_after = next(user for user in users if user["id"] == target["id"])
    assert target_after["ativo"] is True


def test_delete_admin_with_correct_operator_password_is_allowed(client, admin_headers):
    operator = _current_operator(client, admin_headers)
    target = _create_admin_target(client, admin_headers)
    assert target["id"] != operator["id"]
    assert TARGET_PASSWORD != OPERATOR_PASSWORD

    response = client.request(
        "DELETE",
        f"/api/usuarios/{target['id']}",
        headers=admin_headers,
        json={"senha": OPERATOR_PASSWORD},
    )

    assert response.status_code == 204


def test_deactivate_admin_with_correct_operator_password_is_allowed(client, admin_headers):
    operator = _current_operator(client, admin_headers)
    target = _create_admin_target(client, admin_headers)
    assert target["id"] != operator["id"]
    assert TARGET_PASSWORD != OPERATOR_PASSWORD

    response = client.patch(
        f"/api/usuarios/{target['id']}/status",
        headers=admin_headers,
        json={"ativo": False, "senha": OPERATOR_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json()["ativo"] is False


def test_delete_self_remains_blocked_when_another_admin_exists(client, admin_headers):
    operator = _current_operator(client, admin_headers)
    _create_admin_target(client, admin_headers)

    response = client.request(
        "DELETE",
        f"/api/usuarios/{operator['id']}",
        headers=admin_headers,
        json={"senha": OPERATOR_PASSWORD},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "O usuário logado não pode ser excluído"


def test_non_admin_status_change_does_not_require_operation_password(client, admin_headers):
    target = _create_non_admin_target(client, admin_headers)

    response = client.patch(
        f"/api/usuarios/{target['id']}/status",
        headers=admin_headers,
        json={"ativo": False},
    )

    assert response.status_code == 200
    assert response.json()["ativo"] is False


def test_admin_activation_does_not_require_operation_password(client, admin_headers):
    target = _create_admin_target(client, admin_headers)
    deactivated = client.patch(
        f"/api/usuarios/{target['id']}/status",
        headers=admin_headers,
        json={"ativo": False, "senha": OPERATOR_PASSWORD},
    )
    assert deactivated.status_code == 200

    activated = client.patch(
        f"/api/usuarios/{target['id']}/status",
        headers=admin_headers,
        json={"ativo": True},
    )

    assert activated.status_code == 200
    assert activated.json()["ativo"] is True