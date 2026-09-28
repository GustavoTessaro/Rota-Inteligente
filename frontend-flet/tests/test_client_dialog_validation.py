from types import SimpleNamespace
from unittest.mock import MagicMock

import flet as ft
import pytest

from app.application import DeliveryApp


def _make_app():
    app = DeliveryApp.__new__(DeliveryApp)
    app.page = SimpleNamespace(update=MagicMock(), dialog=None)
    app.api = SimpleNamespace(request=MagicMock(return_value={}))
    app.notify = MagicMock()
    app.clients_view = MagicMock()

    def open_dialog(dialog):
        dialog.open = True
        app.page.dialog = dialog

    app.open_dialog = open_dialog
    return app


def _find_text_field(dialog, label):
    return next(
        control
        for control in dialog.content.controls
        if isinstance(control, ft.TextField) and control.label == label
    )


def _find_save_action(dialog):
    return next(
        action
        for action in dialog.actions
        if isinstance(action, ft.FilledButton)
        and action.text == "Salvar"
    )


@pytest.mark.parametrize("email_value", ["", "   "])
def test_client_dialog_accepts_empty_optional_email_and_sends_none(email_value):
    app = _make_app()
    app.client_dialog()
    dialog = app.page.dialog
    email = _find_text_field(dialog, "E-mail")
    _find_text_field(dialog, "Nome").value = "Cliente Teste"
    email.value = email_value

    _find_save_action(dialog).on_click(None)

    assert email.error is None
    app.api.request.assert_called_once_with(
        "POST",
        "/clientes",
        json={
            "nome": "Cliente Teste",
            "cpf_cnpj": None,
            "email": None,
            "telefone": None,
            "observacoes": None,
        },
    )
    assert dialog.open is False


def test_client_dialog_rejects_invalid_email_without_calling_api():
    app = _make_app()
    app.client_dialog()
    dialog = app.page.dialog
    email = _find_text_field(dialog, "E-mail")
    _find_text_field(dialog, "Nome").value = "Cliente Teste"
    email.value = "cliente@dominio"

    _find_save_action(dialog).on_click(None)

    assert email.error == "Informe um e-mail válido."
    error_summary = next(
        control.value
        for control in dialog.content.controls
        if isinstance(control, ft.Text) and "E-mail:" in control.value
    )
    assert "E-mail: informe um e-mail válido." in error_summary
    app.api.request.assert_not_called()
    assert dialog.open is True
    app.page.update.assert_called()


def test_client_dialog_trims_valid_email_in_request_payload():
    app = _make_app()
    app.client_dialog()
    dialog = app.page.dialog
    email = _find_text_field(dialog, "E-mail")
    _find_text_field(dialog, "Nome").value = "Cliente Teste"
    email.value = "  cliente@example.com  "

    _find_save_action(dialog).on_click(None)

    assert email.error is None
    request_payload = app.api.request.call_args.kwargs["json"]
    assert request_payload["email"] == "cliente@example.com"
    assert app.api.request.call_args.args == ("POST", "/clientes")
    assert dialog.open is False
    app.notify.assert_called_once_with("Cliente cadastrado.")
    app.clients_view.assert_called_once_with()


def test_client_dialog_rejects_empty_name_without_calling_api():
    app = _make_app()
    app.client_dialog()
    dialog = app.page.dialog
    name = _find_text_field(dialog, "Nome")
    name.value = ""

    _find_save_action(dialog).on_click(None)

    assert name.error == "Informe pelo menos 2 caracteres."
    assert any(
        isinstance(control, ft.Text)
        and control.value == "Nome: informe pelo menos 2 caracteres."
        for control in dialog.content.controls
    )
    app.api.request.assert_not_called()
    assert dialog.open is True
    app.page.update.assert_called()


def test_client_dialog_rejects_one_character_name_without_calling_api():
    app = _make_app()
    app.client_dialog()
    dialog = app.page.dialog
    name = _find_text_field(dialog, "Nome")
    name.value = "A"

    _find_save_action(dialog).on_click(None)

    assert name.error == "Informe pelo menos 2 caracteres."
    assert any(
        isinstance(control, ft.Text)
        and control.value == "Nome: informe pelo menos 2 caracteres."
        for control in dialog.content.controls
    )
    app.api.request.assert_not_called()
    assert dialog.open is True
    app.page.update.assert_called()


def test_client_dialog_accepts_two_character_name_and_saves():
    app = _make_app()
    app.client_dialog()
    dialog = app.page.dialog
    name = _find_text_field(dialog, "Nome")
    name.value = "AB"

    _find_save_action(dialog).on_click(None)

    assert name.error is None
    assert not any(
        isinstance(control, ft.Text) and "Nome:" in control.value
        for control in dialog.content.controls
    )
    app.api.request.assert_called_once()
    assert app.api.request.call_args.kwargs["json"]["nome"] == "AB"
    assert dialog.open is False


def _make_organization_app():
    app = _make_app()
    app.close_dialog = lambda dialog: setattr(dialog, "open", False)
    app.organizations_view = MagicMock()
    return app


def _prepare_valid_organization_fields(dialog, name_value):
    _find_text_field(dialog, "Nome").value = name_value
    _find_text_field(dialog, "CNPJ").value = "12345678901234"
    _find_text_field(dialog, "E-mail").value = "org@example.com"


def test_organization_dialog_rejects_empty_name_without_calling_api():
    app = _make_organization_app()
    app.organization_dialog()
    dialog = app.page.dialog
    _prepare_valid_organization_fields(dialog, "")
    name = _find_text_field(dialog, "Nome")

    _find_save_action(dialog).on_click(None)

    assert name.error == "Informe pelo menos 2 caracteres."
    assert any(
        isinstance(control, ft.Text)
        and control.value == "Nome: informe pelo menos 2 caracteres."
        for control in dialog.content.controls
    )
    app.api.request.assert_not_called()
    assert dialog.open is True
    app.page.update.assert_called()


def test_organization_dialog_rejects_one_character_name_without_calling_api():
    app = _make_organization_app()
    app.organization_dialog()
    dialog = app.page.dialog
    _prepare_valid_organization_fields(dialog, "A")
    name = _find_text_field(dialog, "Nome")

    _find_save_action(dialog).on_click(None)

    assert name.error == "Informe pelo menos 2 caracteres."
    assert any(
        isinstance(control, ft.Text)
        and control.value == "Nome: informe pelo menos 2 caracteres."
        for control in dialog.content.controls
    )
    app.api.request.assert_not_called()
    assert dialog.open is True
    app.page.update.assert_called()


def test_organization_dialog_accepts_two_character_name_and_saves():
    app = _make_organization_app()
    app.organization_dialog()
    dialog = app.page.dialog
    _prepare_valid_organization_fields(dialog, "AB")
    name = _find_text_field(dialog, "Nome")

    _find_save_action(dialog).on_click(None)

    assert name.error is None
    assert not any(
        isinstance(control, ft.Text) and "Nome:" in control.value
        for control in dialog.content.controls
    )
    app.api.request.assert_called_once()
    assert app.api.request.call_args.args == ("POST", "/organizacoes")
    assert app.api.request.call_args.kwargs["json"]["nome"] == "AB"
    assert dialog.open is False