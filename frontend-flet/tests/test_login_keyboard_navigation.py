from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import flet as ft

from app.application import DeliveryApp


def _walk_controls(control):
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)


def test_login_enter_moves_from_email_to_password_and_submits():
    app = DeliveryApp.__new__(DeliveryApp)
    app.page = MagicMock()
    app.api = SimpleNamespace(login=MagicMock(return_value={"perfil": "ADMIN"}))
    app.show_shell = MagicMock()
    app.notify = MagicMock()

    app.show_login()

    controls = list(_walk_controls(app.page.add.call_args.args[0]))
    email = next(control for control in controls if isinstance(control, ft.TextField) and control.label == "E-mail")
    password = next(control for control in controls if isinstance(control, ft.TextField) and control.label == "Senha")
    email.value = " admin@example.com "
    password.value = "secret"

    with patch.object(password, "focus") as focus:
        email.on_submit(None)
        focus.assert_called_once_with()

    password.on_submit(None)

    app.api.login.assert_called_once_with("admin@example.com", "secret")
    app.show_shell.assert_called_once_with()