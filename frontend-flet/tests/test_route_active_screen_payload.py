from types import SimpleNamespace

from app.application import DeliveryApp


def test_driver_route_snapshot_uses_route_payload_directly():
    route = {
        "entregas": [
            {
                "id": 1,
                "entrega_id": 16,
                "ordem_visita": 1,
                "sequencia_otimizada": 1,
                "status": "AGUARDANDO_COLETA",
                "pedido_id": 17,
                "cliente": {
                    "id": 6,
                    "nome": "IFSC",
                },
                "destino": {
                    "logradouro": "Rua Doutor Aujor Luz",
                    "numero": "432",
                    "bairro": "Santa Catarina",
                    "cidade": "Lages",
                    "estado": "SC",
                },
            },
            {
                "id": 2,
                "entrega_id": 17,
                "ordem_visita": 2,
                "sequencia_otimizada": 2,
                "status": "AGUARDANDO_COLETA",
                "pedido_id": 16,
                "cliente": {
                    "id": 7,
                    "nome": "Mezzalira",
                },
                "destino": {
                    "logradouro": "Rua Heitor Villa-Lobos",
                    "numero": "225",
                    "bairro": "São Francisco",
                    "cidade": "Lages",
                    "estado": "SC",
                },
            },
        ]
    }

    snapshot = DeliveryApp._driver_route_payload_snapshot(route)

    assert len(snapshot) == 2
    assert snapshot[0]["delivery"]["id"] == 16
    assert snapshot[0]["address"]["logradouro"] == "Rua Doutor Aujor Luz"
    assert snapshot[0]["cliente"]["nome"] == "IFSC"
    assert snapshot[1]["order"] == 2


def test_next_driver_stop_uses_proxima_entrega_from_real_payload():
    route = {
        "proxima_entrega": {
            "entrega_id": 16,
            "pedido_id": 17,
            "ordem_visita": 1,
            "status": "AGUARDANDO_COLETA",
            "destino": {
                "logradouro": "Rua Doutor Aujor Luz",
                "numero": "432",
                "bairro": "Santa Catarina",
                "cidade": "Lages",
                "estado": "SC",
            },
        }
    }

    next_stop = DeliveryApp._next_driver_stop_from_payload(route)

    assert next_stop is not None
    assert next_stop["delivery"]["id"] == 16
    assert next_stop["address"]["logradouro"] == "Rua Doutor Aujor Luz"


def test_next_driver_stop_ignores_terminal_proxima_entrega_and_uses_route_sequence():
    route = {
        "proxima_entrega": {"entrega_id": 16, "status": "NAO_ENTREGUE", "ordem_visita": 1},
        "entregas": [
            {"entrega_id": 16, "ordem_visita": 1, "status": "NAO_ENTREGUE", "pedido_id": 17},
            {"entrega_id": 18, "ordem_visita": 2, "status": "EM_ROTA", "pedido_id": 19},
        ],
    }

    next_stop = DeliveryApp._next_driver_stop_from_payload(route)

    assert next_stop is not None
    assert next_stop["delivery"]["id"] == 18


def test_next_driver_stop_advances_after_entregue_using_route_sequence():
    route = {
        "proxima_entrega": {"entrega_id": 16, "status": "ENTREGUE", "ordem_visita": 1},
        "entregas": [
            {"entrega_id": 16, "ordem_visita": 1, "status": "ENTREGUE", "pedido_id": 17},
            {"entrega_id": 18, "ordem_visita": 2, "status": "EM_ROTA", "pedido_id": 19},
        ],
    }

    next_stop = DeliveryApp._next_driver_stop_from_payload(route)

    assert next_stop is not None
    assert next_stop["delivery"]["id"] == 18


def test_driver_route_labels_prefer_customer_name_and_address():
    stop = {
        "cliente": {"nome": "IFSC"},
        "address": {
            "logradouro": "Rua Doutor Aujor Luz",
            "numero": "432",
            "bairro": "Santa Catarina",
            "cidade": "Lages",
            "estado": "SC",
        },
    }

    assert DeliveryApp._driver_stop_label(stop) == "IFSC"
    assert "Rua Doutor Aujor Luz" in DeliveryApp._driver_stop_address(stop)


def test_driver_execution_actions_do_not_include_generic_next_delivery():
    route = {"status": "EM_EXECUCAO", "carga_confirmada": True}
    actions = DeliveryApp._driver_execution_action_labels(route)

    assert "Revisar carga" not in actions
    assert "Próxima entrega" not in actions
    assert "Entregue" in actions
    assert "Não entregue" in actions
    assert "Registrar ocorrência" in actions


def test_loading_actions_are_exclusive_before_and_after_confirmation():
    assert DeliveryApp._driver_loading_action_labels({"carga_confirmada": False}) == ["Verificar carga", "Iniciar viagem"]
    assert DeliveryApp._driver_loading_action_labels({"carga_confirmada": True}) == ["Revisar carga", "Iniciar viagem"]


def test_loading_dialog_review_mode_does_not_confirm_again():
    assert DeliveryApp._loading_dialog_action_labels(review_only=True) == ["Fechar"]
    assert DeliveryApp._loading_dialog_action_labels(review_only=False) == ["Cancelar", "Confirmar carga"]


def test_receipt_action_returns_to_active_route():
    app = DeliveryApp.__new__(DeliveryApp)
    calls = []
    app.driver_route_view = lambda route_id: calls.append(("route", route_id))
    app.deliveries_view = lambda: calls.append(("deliveries", None))

    app._refresh_after_delivery_action(42)

    assert calls == [("route", 42)]


def test_review_loading_dialog_is_read_only():
    app = DeliveryApp.__new__(DeliveryApp)
    app.page = SimpleNamespace(dialog=None)
    app.open_dialog = lambda dialog: setattr(app.page, "dialog", dialog)
    app.close_dialog = lambda dialog: None
    route = {"id": 42, "carga_confirmada": True}
    stops = [{"delivery": {"id": 7, "pedido_id": 8}, "cliente": {"nome": "Cliente"}, "address": {}, "order": 1}]

    app.loading_order_dialog(route, stops, review_only=True)

    assert route["carga_confirmada"] is True
    assert [action.text for action in app.page.dialog.actions] == ["Fechar"]


def test_map_current_stop_uses_the_same_next_stop_as_route_cards():
    next_stop = {"delivery": {"id": 18}}

    assert DeliveryApp._map_current_delivery_id(next_stop) == 18


def test_route_completion_summary_separates_delivery_outcomes():
    route = {
        "status": "FINALIZADA",
        "progresso_percentual": 100,
        "entregas": [
            {"status": "ENTREGUE"},
            {"status": "NAO_ENTREGUE"},
            {"status": "CANCELADA"},
        ],
    }

    assert DeliveryApp._route_completion_summary(route) == {
        "entregues": 1,
        "nao_entregues": 1,
        "canceladas": 1,
        "total": 3,
        "progresso": 100,
    }


def test_active_route_404_is_expected_after_finalization():
    assert DeliveryApp._is_expected_route_completion_error("Nenhuma rota ativa para este motorista") is True
    assert DeliveryApp._is_expected_route_completion_error("Falha de conexão") is False


def test_final_route_is_loaded_by_id_after_active_route_404():
    app = DeliveryApp.__new__(DeliveryApp)
    app.api = SimpleNamespace(request=lambda method, path: {"id": 42, "status": "FINALIZADA"})

    route = app._load_completed_route(42)

    assert route["id"] == 42
    assert route["status"] == "FINALIZADA"


def test_final_route_view_renders_completion_summary():
    app = DeliveryApp.__new__(DeliveryApp)
    app.content = SimpleNamespace(controls=[])
    app.page = SimpleNamespace(update=lambda: None)
    app.header_bar = lambda *args, **kwargs: "header"
    app.dashboard_view = lambda: None
    app._driver_route_snapshot = lambda route: []
    app._render_driver_map_native = lambda route, stops, next_stop: "map"
    route = {
        "id": 42,
        "nome": "Rota teste",
        "status": "FINALIZADA",
        "progresso_percentual": 100,
        "entregas": [{"status": "ENTREGUE"}, {"status": "NAO_ENTREGUE"}],
        "distancia_prevista": 12,
        "duracao_prevista": 2,
    }

    app._render_completed_route_view(route)

    summary_controls = app.content.controls[1].content.controls
    summary_text = [control.value for control in summary_controls if hasattr(control, "value")]
    assert "Rota concluída" in summary_text
    assert "Entregues: 1" in summary_text
    assert "Não entregues: 1" in summary_text
