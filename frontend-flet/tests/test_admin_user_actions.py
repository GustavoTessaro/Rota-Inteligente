from types import SimpleNamespace
from unittest.mock import MagicMock

import flet as ft
import pytest

from app.api_client import ApiError
from app.application import DeliveryApp


def _make_app(users, operation_error=None):
    app = DeliveryApp.__new__(DeliveryApp)
    app.page = SimpleNamespace(update=MagicMock(), dialog=None)
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return users
        if operation_error is not None:
            raise operation_error
        return None

    app.api = SimpleNamespace(request=MagicMock(side_effect=request))
    app.notify = MagicMock()
    app.users_view = MagicMock()

    def open_dialog(dialog):
        dialog.open = True
        app.page.dialog = dialog

    app.open_dialog = open_dialog
    app.close_dialog = lambda dialog: setattr(dialog, "open", False)
    app.api_calls = calls
    return app


def _admin(user_id, *, active=True):
    return {
        "id": user_id,
        "nome": f"Admin {user_id}",
        "perfil": "ADMIN",
        "ativo": active,
    }


def _find_password_field(dialog):
    return next(
        control
        for control in dialog.content.controls
        if isinstance(control, ft.TextField)
        and control.label == "Senha do usuário autenticado"
    )


def _find_action(dialog, text):
    return next(action for action in dialog.actions if action.text == text)


def _walk_controls(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)
    trailing = getattr(control, "trailing", None)
    if trailing is not None:
        yield from _walk_controls(trailing)


@pytest.mark.parametrize("operation", ["delete", "deactivate"])
def test_only_admin_is_blocked_with_friendly_message_before_password(operation):
    target = _admin(1)
    app = _make_app([target])

    if operation == "delete":
        app.confirm_delete_user(target)
        expected_message = (
            "Não é possível excluir o único ADMIN cadastrado. "
            "Cadastre outro ADMIN antes de realizar esta operação."
        )
    else:
        app.set_user_status(target["id"], False, user=target)
        expected_message = (
            "Não é possível desativar o único ADMIN cadastrado. "
            "Cadastre outro ADMIN antes de realizar esta operação."
        )

    assert app.page.dialog is None
    app.notify.assert_called_once_with(expected_message, True)
    assert app.api.request.call_count == 1
    assert app.api_calls[0][0:2] == ("GET", "/usuarios?limit=100&offset=0")


@pytest.mark.parametrize(
    ("operation", "expected_call"),
    [
        (
            "delete",
            ("DELETE", "/usuarios/2", {"json": {"senha": "operator-password"}}),
        ),
        (
            "deactivate",
            (
                "PATCH",
                "/usuarios/2/status",
                {"json": {"ativo": False, "senha": "operator-password"}},
            ),
        ),
    ],
)
def test_admin_sensitive_action_requests_password_and_sends_it(operation, expected_call):
    target = _admin(2)
    app = _make_app([_admin(1), target])

    if operation == "delete":
        app.confirm_delete_user(target)
    else:
        app.set_user_status(target["id"], False, user=target)

    dialog = app.page.dialog
    password = _find_password_field(dialog)
    assert len(app.api_calls) == 1
    assert app.api_calls[0][0:2] == ("GET", "/usuarios?limit=100&offset=0")

    password.value = "operator-password"
    _find_action(dialog, "Confirmar").on_click(None)

    assert app.api_calls[-1] == expected_call
    assert dialog.open is False
    app.notify.assert_called_once()
    app.users_view.assert_called_once_with()


def test_admin_sensitive_action_keeps_dialog_open_on_api_password_error():
    target = _admin(2)
    app = _make_app(
        [_admin(1), target],
        operation_error=ApiError("Senha do usuário autenticado inválida"),
    )
    app.confirm_delete_user(target)
    dialog = app.page.dialog
    _find_password_field(dialog).value = "wrong-password"

    _find_action(dialog, "Confirmar").on_click(None)

    error_messages = [
        control.value
        for control in dialog.content.controls
        if isinstance(control, ft.Text) and control.value
    ]
    assert "Senha do usuário autenticado inválida" in error_messages
    assert dialog.open is True
    app.users_view.assert_not_called()


def test_non_admin_status_change_keeps_existing_immediate_flow():
    manager = {"id": 3, "nome": "Gestor", "perfil": "GESTOR", "ativo": True}
    app = _make_app([])

    app.set_user_status(manager["id"], False, user=manager)

    assert app.api_calls == [
        ("PATCH", "/usuarios/3/status", {"json": {"ativo": False}})
    ]
    app.notify.assert_called_once_with("Usuário desativado.")
    app.users_view.assert_called_once_with()


def test_admin_activation_keeps_existing_flow_without_password_prompt():
    target = _admin(2, active=False)
    app = _make_app([_admin(1), target])

    app.set_user_status(target["id"], True, user=target)

    assert app.api_calls == [
        ("PATCH", "/usuarios/2/status", {"json": {"ativo": True}})
    ]
    assert app.page.dialog is None
    app.notify.assert_called_once_with("Usuário ativado.")
    app.users_view.assert_called_once_with()


def test_users_view_toggle_colors_reflect_active_state():
    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "ADMIN"}
    app.page = SimpleNamespace(update=MagicMock())
    app.content = ft.Column(controls=[])
    app.api = SimpleNamespace(request=MagicMock(return_value=[
        {"id": 1, "nome": "Ativo", "email": "ativo@example.com", "perfil": "GESTOR", "ativo": True},
        {"id": 2, "nome": "Inativo", "email": "inativo@example.com", "perfil": "GESTOR", "ativo": False},
    ]))

    app.users_view()

    toggles = {
        control.tooltip: control
        for control in _walk_controls(app.content)
        if isinstance(control, ft.IconButton)
        and control.tooltip in {"Desativar usuário", "Ativar usuário"}
    }

    active_toggle = toggles["Desativar usuário"]
    inactive_toggle = toggles["Ativar usuário"]
    assert active_toggle.icon == ft.Icons.TOGGLE_ON
    assert active_toggle.icon_color == ft.Colors.GREEN
    assert inactive_toggle.icon == ft.Icons.TOGGLE_OFF
    assert inactive_toggle.icon_color == ft.Colors.RED
    assert active_toggle.bgcolor is None
    assert inactive_toggle.bgcolor is None


def test_client_and_product_toggles_use_active_state_colors():
    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "ADMIN"}
    app.page = SimpleNamespace(update=MagicMock())
    app.content = ft.Column(controls=[])
    clients = [
        {"id": 1, "nome": "Cliente Ativo", "email": "ativo@example.com", "telefone": None, "cpf_cnpj": None, "ativo": True},
        {"id": 2, "nome": "Cliente Inativo", "email": "inativo@example.com", "telefone": None, "cpf_cnpj": None, "ativo": False},
    ]
    products = [
        {"id": 3, "nome": "Produto Ativo", "descricao": "", "valor_declarado": 12.5, "peso": 1, "ativo": True},
        {"id": 4, "nome": "Produto Inativo", "descricao": "", "valor_declarado": 8.0, "peso": 2, "ativo": False},
    ]

    def request(method, path, **kwargs):
        if path.startswith("/clientes?"):
            return clients
        if path.startswith("/produtos?"):
            return products
        raise AssertionError(f"Unexpected request: {method} {path}")

    app.api = SimpleNamespace(request=MagicMock(side_effect=request))
    app.clients_view()
    client_toggles = {
        control.tooltip: control
        for control in _walk_controls(app.content)
        if isinstance(control, ft.IconButton)
        and control.tooltip in {"Desativar cliente", "Ativar cliente"}
    }
    app.products_view()
    product_toggles = {
        control.tooltip: control
        for control in _walk_controls(app.content)
        if isinstance(control, ft.IconButton)
        and control.tooltip in {"Desativar produto", "Ativar produto"}
    }
    toggles = {**client_toggles, **product_toggles}

    expected = {
        "Desativar cliente": (ft.Icons.TOGGLE_ON, ft.Colors.GREEN),
        "Ativar cliente": (ft.Icons.TOGGLE_OFF, ft.Colors.RED),
        "Desativar produto": (ft.Icons.TOGGLE_ON, ft.Colors.GREEN),
        "Ativar produto": (ft.Icons.TOGGLE_OFF, ft.Colors.RED),
    }
    for tooltip, (icon, color) in expected.items():
        toggle = toggles[tooltip]
        assert toggle.icon == icon
        assert toggle.icon_color == color
        assert toggle.on_click is not None
        assert toggle.bgcolor is None