from types import SimpleNamespace
from unittest.mock import MagicMock

from app.application import DeliveryApp


def test_notify_success_uses_snackbar():
    page = SimpleNamespace(show_snack_bar=MagicMock(), update=MagicMock(), dialog=None)
    app = DeliveryApp(page)

    app.notify("Operação concluída com sucesso.")

    page.show_snack_bar.assert_called_once()
    assert page.dialog is None or getattr(page.dialog, "open", False) is False


def test_notify_error_uses_dialog_for_ui_visibility():
    page = SimpleNamespace(show_snack_bar=MagicMock(), update=MagicMock(), dialog=None)
    app = DeliveryApp(page)

    app.notify("A organização selecionada não possui um endereço principal geocodificado.", error=True)

    assert page.dialog is not None, "Erro deve abrir um dialog na UI."
    assert page.dialog.open is True, "Dialog de erro deve ficar aberto na interface."
    page.show_snack_bar.assert_not_called()


if __name__ == "__main__":
    test_notify_success_uses_snackbar()
    test_notify_error_uses_dialog_for_ui_visibility()
    print("ok")
