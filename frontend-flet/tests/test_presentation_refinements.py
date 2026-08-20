from types import SimpleNamespace
from unittest.mock import MagicMock

import flet as ft

from app.application import DeliveryApp


def test_format_iso_datetime_for_display():
    assert DeliveryApp._format_iso_datetime("2026-08-20T17:08:48.517462") == "20/08/2026 17:08"


def test_format_iso_datetime_handles_empty_and_invalid_values():
    assert DeliveryApp._format_iso_datetime(None) == "--"
    assert DeliveryApp._format_iso_datetime("") == "--"
    assert DeliveryApp._format_iso_datetime("data desconhecida") == "data desconhecida"


def test_route_distance_prefers_real_and_falls_back_to_expected():
    assert DeliveryApp._route_distance_display({"distancia_real": 8.77, "distancia_prevista": 12.0}) == "8,77 km"
    assert DeliveryApp._route_distance_display({"distancia_real": 0, "distancia_prevista": 12.0}) == "12,00 km"
    assert DeliveryApp._route_distance_display({"distancia_real": None, "distancia_prevista": None}) == "--"


def test_route_duration_formats_minutes_and_hours_without_persistence_change():
    assert DeliveryApp._route_duration_display({"duracao_real": 0.4, "duracao_prevista": 1.0}) == "24 min"
    assert DeliveryApp._route_duration_display({"duracao_real": 0, "duracao_prevista": 1.0}) == "1 h 0 min"
    assert DeliveryApp._route_duration_display({"duracao_real": None, "duracao_prevista": None}) == "--"


def test_history_modal_uses_related_objects_and_formatted_dates():
    page = MagicMock(spec=ft.Page)
    app = DeliveryApp(page)
    app.user = {"perfil": "MOTORISTA"}
    app.open_dialog = MagicMock()
    route = {
        "id": 7,
        "nome": "Rota Histórica",
        "descricao": None,
        "status": "FINALIZADA",
        "organizacao_id": 3,
        "organizacao": {"id": 3, "nome": "Angeloni"},
        "motorista_id": 4,
        "motorista": {"id": 4, "nome": "Motorista 1"},
        "veiculo_id": 1,
        "veiculo": {"id": 1, "marca": "Fiat", "modelo": "Ducato", "placa": "ABC1234"},
        "entregas": [],
        "data_planejada": "2026-08-20T17:08:48.517462",
        "data_inicio": None,
        "data_conclusao": None,
        "progresso_percentual": 100,
    }

    app.route_details_dialog(route)
    dialog = app.open_dialog.call_args.args[0]
    text_values = [control.value for control in dialog.content.controls if isinstance(control, ft.Text)]

    assert "Organização: Angeloni" in text_values
    assert "Motorista: Motorista 1" in text_values
    assert "Veículo: Fiat Ducato · ABC1234" in text_values
    assert "Data planejada: 20/08/2026 17:08" in text_values


def test_profile_displays_organization_name_when_available():
    page = MagicMock(spec=ft.Page)
    app = DeliveryApp(page)
    app.user = {
        "nome": "Motorista 1",
        "email": "motorista@example.com",
        "telefone": "11999999999",
        "perfil": "MOTORISTA",
        "ativo": True,
        "organizacao_id": 3,
        "organizacao": {"id": 3, "nome": "Angeloni"},
    }

    app.profile_view()
    text_values = []
    for control in app.content.controls:
        if isinstance(control, ft.Container) and isinstance(control.content, ft.Column):
            for child in control.content.controls:
                if isinstance(child, ft.Container) and isinstance(child.content, ft.Column):
                    text_values.extend(item.value for item in child.content.controls if isinstance(item, ft.Text))
                if isinstance(child, ft.Column):
                    for field in child.controls:
                        if isinstance(field, ft.Container) and isinstance(field.content, ft.Column):
                            text_values.extend(item.value for item in field.content.controls if isinstance(item, ft.Text))

    assert "Organização" in text_values
    assert "Angeloni" in text_values
