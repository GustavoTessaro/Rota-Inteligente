import pytest


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


def _manager_login(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "gestor1@sistema.com", "senha": "123456"},
    )
    assert response.status_code == 200
    return response.json()


def test_manager_lists_only_motorists_from_own_organization(client):
    manager_login = _manager_login(client)
    manager = manager_login["usuario"]

    response = client.get(
        "/api/usuarios?limit=100&offset=0",
        headers={"Authorization": f"Bearer {manager_login['token']}"},
    )

    assert response.status_code == 200
    users = response.json()
    assert users
    assert all(user["perfil"] == "MOTORISTA" for user in users)
    assert all(user["organizacao_id"] == manager["organizacao_id"] for user in users)


@pytest.mark.parametrize("profile", ["ADMIN", "GESTOR"])
def test_manager_cannot_create_non_motorist(client, profile):
    manager_login = _manager_login(client)
    manager = manager_login["usuario"]

    response = client.post(
        "/api/usuarios",
        headers={"Authorization": f"Bearer {manager_login['token']}"},
        json={
            "nome": f"Usuário {profile}",
            "email": f"manager.cannot.create.{profile.lower()}@example.com",
            "senha": "123456",
            "perfil": profile,
            "organizacao_id": manager["organizacao_id"],
        },
    )

    assert response.status_code == 403


def test_manager_can_create_and_edit_motorist_in_own_organization(client, admin_headers):
    manager_login = _manager_login(client)
    manager = manager_login["usuario"]
    manager_headers = {"Authorization": f"Bearer {manager_login['token']}"}
    created = client.post(
        "/api/usuarios",
        headers=manager_headers,
        json={
            "nome": "Motorista do Gestor",
            "email": "manager.created.driver@example.com",
            "senha": "123456",
            "perfil": "MOTORISTA",
        },
    )

    assert created.status_code == 201, created.text
    driver = created.json()
    assert driver["perfil"] == "MOTORISTA"
    assert driver["organizacao_id"] == manager["organizacao_id"]

    updated = client.put(
        f"/api/usuarios/{driver['id']}",
        headers=manager_headers,
        json={
            "nome": "Motorista Atualizado",
            "email": "manager.created.driver@example.com",
            "senha": None,
            "perfil": "MOTORISTA",
            "organizacao_id": manager["organizacao_id"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["nome"] == "Motorista Atualizado"

    changed_role = client.put(
        f"/api/usuarios/{driver['id']}",
        headers=manager_headers,
        json={
            "nome": "Motorista Atualizado",
            "email": "manager.created.driver@example.com",
            "senha": None,
            "perfil": "GESTOR",
            "organizacao_id": manager["organizacao_id"],
        },
    )
    assert changed_role.status_code == 403


def test_manager_cannot_modify_users_outside_motorist_organization(client, admin_headers):
    manager_login = _manager_login(client)
    manager = manager_login["usuario"]
    manager_headers = {"Authorization": f"Bearer {manager_login['token']}"}
    organizations = client.get("/api/organizacoes", headers=admin_headers).json()
    other_organization_id = next(
        item["id"] for item in organizations if item["id"] != manager["organizacao_id"]
    )
    other_driver = client.post(
        "/api/usuarios",
        headers=admin_headers,
        json={
            "nome": "Motorista de Outra Organização",
            "email": "manager.outside.driver@example.com",
            "senha": "123456",
            "perfil": "MOTORISTA",
            "organizacao_id": other_organization_id,
        },
    )
    other_manager = client.post(
        "/api/usuarios",
        headers=admin_headers,
        json={
            "nome": "Gestor da Organização",
            "email": "manager.sameorg.target@example.com",
            "senha": "123456",
            "perfil": "GESTOR",
            "organizacao_id": manager["organizacao_id"],
        },
    )
    assert other_driver.status_code == 201, other_driver.text
    assert other_manager.status_code == 201, other_manager.text

    foreign_create = client.post(
        "/api/usuarios",
        headers=manager_headers,
        json={
            "nome": "Motorista Fora do Escopo",
            "email": "manager.foreign.create@example.com",
            "senha": "123456",
            "perfil": "MOTORISTA",
            "organizacao_id": other_organization_id,
        },
    )
    assert foreign_create.status_code == 403

    for target in (other_driver.json(), other_manager.json()):
        update = client.put(
            f"/api/usuarios/{target['id']}",
            headers=manager_headers,
            json={
                "nome": target["nome"],
                "email": target["email"],
                "senha": None,
                "perfil": "MOTORISTA",
                "organizacao_id": manager["organizacao_id"],
            },
        )
        status = client.patch(
            f"/api/usuarios/{target['id']}/status",
            headers=manager_headers,
            json={"ativo": False},
        )
        delete = client.delete(
            f"/api/usuarios/{target['id']}",
            headers=manager_headers,
        )
        assert update.status_code == 403
        assert status.status_code == 403
        assert delete.status_code == 403