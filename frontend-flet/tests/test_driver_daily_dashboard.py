from unittest.mock import MagicMock

import flet as ft

from app.application import DeliveryApp


class SummaryApi:
    def __init__(self, summary, active_route=None):
        self.summary = summary
        self.active_route = active_route
        self.calls = []
        self.token = "token"

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/rotas/motorista/resumo-diario":
            return self.summary
        if path == "/rotas/motorista/atual":
            return self.active_route
        raise AssertionError(f"Chamada inesperada: {method} {path}")


def _app(summary, active_route=None):
    app = DeliveryApp(MagicMock(spec=ft.Page))
    app.user = {"nome": "Motorista", "perfil": "MOTORISTA"}
    app.api = SummaryApi(summary, active_route)
    return app


def _text_values(control):
    values = []
    if isinstance(control, ft.Text):
        values.append(control.value)
    if hasattr(control, "controls") and control.controls:
        for child in control.controls:
            values.extend(_text_values(child))
    if hasattr(control, "content") and control.content:
        values.extend(_text_values(control.content))
    return values


def _summary(**overrides):
    data = {
        "data": "2026-08-20",
        "entregas_concluidas_hoje": 3,
        "entregas_nao_entregues_hoje": 1,
        "entregas_pendentes": 2,
        "rotas_concluidas_hoje": 2,
        "distancia_hoje_km": 18.4,
        "tempo_em_rota_hoje_minutos": 102,
        "veiculo_atual": {"id": 1, "placa": "ABC1234", "marca": "Fiat", "modelo": "Ducato"},
        "rota_atual": None,
    }
    data.update(overrides)
    return data


def test_dashboard_without_active_route_uses_daily_history_and_no_admin_calls():
    app = _app(_summary())
    app.driver_dashboard_view()
    values = _text_values(app.content)

    assert "3" in values
    assert "2" in values
    assert "18,4 km" in values
    assert "1h 42min" in values
    assert "Ducato (ABC1234)" in values
    assert "/rotas/motorista/resumo-diario" in [path for _, path, _ in app.api.calls]
    assert "/rotas/motorista/atual" not in [path for _, path, _ in app.api.calls]
    assert all("/relatorios" not in path and "/organizacoes" not in path for _, path, _ in app.api.calls)


def test_dashboard_zero_state_uses_numeric_zeros():
    app = _app(_summary(
        entregas_concluidas_hoje=0,
        entregas_nao_entregues_hoje=0,
        entregas_pendentes=0,
        rotas_concluidas_hoje=0,
        distancia_hoje_km=0,
        tempo_em_rota_hoje_minutos=0,
        veiculo_atual=None,
    ))
    app.driver_dashboard_view()
    values = _text_values(app.content)

    assert "0" in values
    assert "0 km" in values
    assert "0 min" in values
    assert "Nenhuma rota atribuída no momento" in values


def test_dashboard_active_route_uses_summary_vehicle_and_loads_mission_payload():
    route_summary = {"id": 8, "nome": "Rota Atual", "status": "EM_EXECUCAO", "progresso_percentual": 66}
    active_route = {
        "id": 8,
        "nome": "Rota Atual",
        "status": "EM_EXECUCAO",
        "veiculo": {"placa": "XYZ9999", "modelo": "Van"},
        "entregas": [],
    }
    app = _app(_summary(
        veiculo_atual={"id": 1, "placa": "ABC1234", "marca": "Fiat", "modelo": "Ducato"},
        rota_atual=route_summary,
    ), active_route)
    app.driver_dashboard_view()
    values = _text_values(app.content)

    assert "Van (XYZ9999)" in values
    assert "/rotas/motorista/resumo-diario" in [path for _, path, _ in app.api.calls]
    assert "/rotas/motorista/atual" in [path for _, path, _ in app.api.calls]
    assert "Nenhuma rota atribuída no momento" not in values


def test_dashboard_vehicle_falls_back_to_driver_linked_vehicle_without_active_route():
    app = _app(_summary(veiculo_atual={"id": 4, "placa": "DEF4567", "marca": "Ford", "modelo": "Transit"}))
    app.driver_dashboard_view()
    values = _text_values(app.content)
    assert "Transit (DEF4567)" in values


def test_dashboard_mission_empty_state_remains_available():
    app = _app(_summary(veiculo_atual=None, rota_atual=None))
    app.driver_dashboard_view()
    assert "Nenhuma rota atribuída no momento" in _text_values(app.content)


def test_dashboard_format_helpers():
    assert DeliveryApp._format_dashboard_distance(18.4) == "18,4 km"
    assert DeliveryApp._format_dashboard_distance(0) == "0 km"
    assert DeliveryApp._format_dashboard_duration(42) == "42 min"
    assert DeliveryApp._format_dashboard_duration(102) == "1h 42min"
    assert DeliveryApp._format_dashboard_duration(0) == "0 min"
