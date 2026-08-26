from datetime import datetime
from threading import Event

import pytest

from app.driver_location_tracking import DriverLocationTracking, LocationSample


def sample(**changes):
    values = {
        "latitude": -27.815,
        "longitude": -50.326,
        "accuracy": 10,
        "speed": 32,
        "heading": 90,
        "timestamp": datetime.now().isoformat(),
    }
    values.update(changes)
    return LocationSample(**values)


def test_start_requires_execution_route_and_vehicle():
    service = DriverLocationTracking(lambda: sample(), lambda route_id, payload: None)

    with pytest.raises(ValueError):
        service.start(route_id=None, route_status="EM_EXECUCAO", vehicle_id=1)
    with pytest.raises(ValueError):
        service.start(route_id=7, route_status="PRONTA", vehicle_id=1)
    with pytest.raises(ValueError):
        service.start(route_id=7, route_status="EM_EXECUCAO", vehicle_id=None)


def test_start_is_idempotent_and_stop_is_explicit():
    service = DriverLocationTracking(lambda: None, lambda route_id, payload: None, interval=60)

    assert service.start(7, "EM_EXECUCAO", 1) is True
    assert service.start(7, "EM_EXECUCAO", 1) is False
    assert service.active is True

    service.stop()

    assert service.active is False


def test_status_pause_and_terminal_states_stop_service():
    service = DriverLocationTracking(lambda: None, lambda route_id, payload: None, interval=60)
    service.start(7, "EM_EXECUCAO", 1)

    service.update_route_status("PAUSADA")
    assert service.active is False

    service.start(7, "EM_EXECUCAO", 1)
    service.update_route_status("FINALIZADA")
    assert service.active is False

    service.start(7, "EM_EXECUCAO", 1)
    service.update_route_status("CANCELADA")
    assert service.active is False


def test_valid_position_is_published_with_route_id_and_without_forged_identity():
    published = []
    service = DriverLocationTracking(lambda: sample(), lambda route_id, payload: published.append((route_id, payload)), interval=60)

    assert service.publish_sample(sample()) is False
    assert published == []
    service.start(8, "EM_EXECUCAO", 3)
    assert service.publish_sample(sample()) is True
    service.stop()
    route_id, payload = published[-1]
    assert route_id == 8
    assert payload["latitude"] == -27.815
    assert payload["longitude"] == -50.326
    assert payload["velocidade"] == 32
    assert "speed" not in payload
    assert "motorista_id" not in payload
    assert "veiculo_id" not in payload


def test_api_client_publishes_position_to_route_endpoint():
    from unittest.mock import MagicMock
    from app.api_client import ApiClient

    client = ApiClient()
    client.request = MagicMock(return_value={"id": 1})
    payload = {"latitude": -27.815, "longitude": -50.326, "timestamp": "now"}

    assert client.publish_route_position(8, payload) == {"id": 1}
    client.request.assert_called_once_with("POST", "/rotas/8/posicoes", json=payload)


def test_delivery_app_starts_tracking_only_for_motorista_execution_route():
    from unittest.mock import MagicMock
    from app.application import DeliveryApp

    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "MOTORISTA"}
    app.driver_location_tracking = MagicMock()
    route = {"id": 8, "status": "EM_EXECUCAO", "veiculo_id": 3, "veiculo": {"id": 3}}

    DeliveryApp._sync_driver_tracking(app, route)

    app.driver_location_tracking.start.assert_called_once_with(8, "EM_EXECUCAO", 3)
    assert app.gps_tracking_state == "gps_ativo"


def test_delivery_app_stops_tracking_for_paused_or_terminal_route():
    from unittest.mock import MagicMock
    from app.application import DeliveryApp

    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "MOTORISTA"}
    app.driver_location_tracking = MagicMock()

    for status in ("PAUSADA", "FINALIZADA", "CANCELADA"):
        DeliveryApp._sync_driver_tracking(app, {"id": 8, "status": status, "veiculo_id": 3})

    assert app.driver_location_tracking.stop.call_count == 3
    assert app.gps_tracking_state == "inativo"


def test_delivery_app_classifies_tracking_errors_for_driver_status():
    from unittest.mock import MagicMock
    from app.application import DeliveryApp
    from app.geolocation_provider import GeolocationPermissionDenied, GeolocationServiceUnavailable

    app = DeliveryApp.__new__(DeliveryApp)
    app.driver_location_tracking = MagicMock()

    DeliveryApp._handle_driver_tracking_error(app, GeolocationPermissionDenied("denied"))
    assert app.gps_tracking_state == "aguardando_permissao"
    DeliveryApp._handle_driver_tracking_error(app, GeolocationServiceUnavailable("disabled"))
    assert app.gps_tracking_state == "localizacao_indisponivel"
    DeliveryApp._handle_driver_tracking_error(app, RuntimeError("offline"))
    assert app.gps_tracking_state == "erro_temporario"


def test_driver_gps_status_labels_are_safe_for_ui():
    from app.application import DeliveryApp

    assert DeliveryApp._gps_status_label("gps_ativo") == "GPS ativo"
    assert DeliveryApp._gps_status_label("aguardando_permissao") == "Aguardando permissão de localização"
    assert DeliveryApp._gps_status_label("localizacao_indisponivel") == "Localização indisponível"
    assert DeliveryApp._gps_status_label("erro_temporario") == "Erro temporário no envio da localização"
    assert DeliveryApp._gps_status_label("inativo") == "GPS inativo"


def test_invalid_coordinates_and_accuracy_are_discarded():
    published = []
    service = DriverLocationTracking(lambda: sample(), lambda route_id, payload: published.append(payload), interval=60)
    service.start(7, "EM_EXECUCAO", 1)

    service.publish_sample(sample(latitude=91))
    service.publish_sample(sample(longitude=-181))
    service.publish_sample(sample(accuracy=None))
    service.publish_sample(sample(accuracy=101))

    assert published == []


def test_network_error_does_not_stop_active_service():
    attempts = []
    ready = Event()

    def publish(route_id, payload):
        attempts.append(payload)
        ready.set()
        raise RuntimeError("offline")

    service = DriverLocationTracking(lambda: sample(), publish, interval=0.01)
    service.start(7, "EM_EXECUCAO", 1)
    assert service.publish_sample(sample()) is False

    assert ready.wait(1)
    assert service.active is True
    service.stop()


def test_network_error_notifies_without_deactivating_service():
    errors = []
    service = DriverLocationTracking(
        lambda: sample(),
        lambda route_id, payload: (_ for _ in ()).throw(RuntimeError("offline")),
        interval=60,
        on_error=errors.append,
    )
    service.start(7, "EM_EXECUCAO", 1)
    service.publish_sample(sample())
    service.stop()

    assert len(errors) == 1
    assert service.active is False
