import asyncio
from types import SimpleNamespace

from app.application import DeliveryApp


class FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path))
        return self.responses.get(path, [])


def test_complete_route_payload_does_not_resolve_client_by_id():
    app = DeliveryApp.__new__(DeliveryApp)
    api = FakeApi({"/pedidos/17": {"cliente_id": 8}})
    app.api = api
    route = {
        "entregas": [{
            "entrega_id": 16,
            "pedido_id": 17,
            "ordem_visita": 1,
            "sequencia_otimizada": 1,
            "status": "EM_ROTA",
            "cliente": {"id": 8, "nome": "Martendal"},
            "destino": {"logradouro": "Rua A", "numero": "1"},
        }],
    }

    snapshot = app._driver_route_snapshot(route)

    assert snapshot[0]["cliente"]["nome"] == "Martendal"
    assert all(path != "/clientes/8" for _, path in api.calls)
    assert api.calls == []


def test_delivery_management_lookup_fetches_clients_once_and_addresses_once_per_client():
    app = DeliveryApp.__new__(DeliveryApp)
    api = FakeApi({
        "/clientes": [{"id": 8, "nome": "Martendal"}],
        "/clientes/8/enderecos": [{"id": 80, "logradouro": "Rua A"}],
    })
    app.api = api

    clients_by_id, addresses_by_client = app._load_client_lookup(
        [{"cliente_id": 8}, {"cliente_id": 8}, {"cliente_id": 8}]
    )

    assert clients_by_id[8]["nome"] == "Martendal"
    assert addresses_by_client[8][0]["id"] == 80
    assert api.calls == [("GET", "/clientes"), ("GET", "/clientes/8/enderecos")]


def test_websocket_disconnect_signals_listener_without_direct_close():
    app = DeliveryApp.__new__(DeliveryApp)
    close_calls = []
    stop_event = asyncio.Event()
    loop = asyncio.new_event_loop()
    app.user = {"perfil": "ADMIN"}
    app.websocket_client = SimpleNamespace(close=lambda: close_calls.append("close"))
    app._tracking_loop = loop
    app._tracking_stop_event = stop_event
    app._set_connection_state = lambda state: None

    loop.call_soon(stop_event.set)
    loop.run_until_complete(asyncio.sleep(0))
    app._disconnect_tracking_socket()

    assert stop_event.is_set()
    assert close_calls == []
    loop.close()


def test_listener_signal_allows_reconnection_state_to_reset():
    app = DeliveryApp.__new__(DeliveryApp)
    app.websocket_client = None
    app._tracking_thread = None
    app._tracking_loop = None
    app._tracking_stop_event = None
    app.user = {"perfil": "ADMIN"}

    assert app._tracking_connection_available() is True
    app.user = None
    assert app._tracking_connection_available() is True
