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