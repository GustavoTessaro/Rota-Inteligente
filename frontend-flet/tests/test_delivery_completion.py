from types import SimpleNamespace

import pytest

from app.api_client import ApiError
from app.application import DeliveryApp


class FakeApi:
    def __init__(self, responses=None, error=None):
        self.calls = []
        self.responses = responses or {}
        self.error = error

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self.error:
            raise self.error
        return self.responses.get((method, path), {})


def _make_app(api):
    app = DeliveryApp.__new__(DeliveryApp)
    app.api = api
    app.page = SimpleNamespace(update=lambda: None, dialog=None)
    def open_dialog(dialog):
        dialog.open = True
        app.page.dialog = dialog

    app.open_dialog = open_dialog
    app.close_dialog = lambda dialog: setattr(dialog, "open", False)
    app.notify = lambda *args: None
    app.driver_route_view = lambda route_id: None
    app.deliveries_view = lambda: None
    return app


def test_active_route_entregue_opens_empty_dialog_without_receipt_get():
    api = FakeApi()
    app = _make_app(api)

    app.receipt_dialog(17, return_route_id=42)

    assert api.calls == []
    assert app.page.dialog.title.value == "Comprovante de entrega"


def test_active_route_save_calls_only_atomic_completion_and_allows_empty_document():
    api = FakeApi(responses={("POST", "/entregas/17/concluir"): {"id": 1}})
    app = _make_app(api)
    refreshed = []
    app.driver_route_view = lambda route_id: refreshed.append(route_id)

    app.receipt_dialog(17, return_route_id=42)
    dialog = app.page.dialog
    fields = dialog.content.controls
    fields[1].value = "Maria"
    fields[2].value = ""
    fields[3].value = "Recebido"
    dialog.actions[-1].on_click(None)

    assert [call[0:2] for call in api.calls] == [("POST", "/entregas/17/concluir")]
    assert api.calls[0][2]["json"] == {
        "nome_recebedor": "Maria",
        "documento_recebedor": None,
        "observacao": "Recebido",
    }
    assert refreshed == [42]


def test_active_route_completion_error_keeps_dialog_open_and_notifies():
    api = FakeApi(error=ApiError("Entrega já processada"))
    app = _make_app(api)

    app.receipt_dialog(17, return_route_id=42)
    dialog = app.page.dialog
    dialog.content.controls[1].value = "Maria"
    dialog.actions[-1].on_click(None)

    assert dialog.open is True
    assert dialog.content.controls[0].value == "Entrega já processada"
