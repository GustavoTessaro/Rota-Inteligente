from datetime import datetime
from unittest.mock import MagicMock, patch

import flet as ft

from app.application import DeliveryApp


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


def _mission_card(status):
    app = DeliveryApp(MagicMock(spec=ft.Page))
    app.user = {"nome": "Motorista", "perfil": "MOTORISTA"}
    return app._build_driver_mission_card({
        "id": 4,
        "nome": "Rota Teste",
        "status": status,
        "organizacao": {"nome": "Angeloni"},
        "entregas": [],
        "distancia_prevista": 4.16,
        "duracao_prevista": 0.16,
    })


def _button_labels(card):
    labels = []
    for control in card.content.controls:
        if isinstance(control, ft.Row):
            for child in control.controls:
                if isinstance(child, ft.FilledButton):
                    labels.append(child.text)
    return labels


def test_generated_route_name_uses_local_datetime_without_utc_timezone():
    with patch("app.application.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 8, 20, 16, 20)
        assert DeliveryApp._generated_route_name() == "Rota gerada 20/08/2026 16:20"
        mocked_datetime.now.assert_called_once_with()


def test_dashboard_mission_label_pronta_is_start():
    assert "Iniciar Rota" in _button_labels(_mission_card("PRONTA"))


def test_dashboard_mission_label_em_execucao_is_continue():
    assert "Continuar Rota" in _button_labels(_mission_card("EM_EXECUCAO"))


def test_dashboard_mission_label_pausada_is_continue():
    assert "Continuar Rota" in _button_labels(_mission_card("PAUSADA"))
