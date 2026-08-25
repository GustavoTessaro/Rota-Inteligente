import flet as ft
import flet_map as fmap

from app.map_view import MapView


def _marker(vehicle_id, latitude, longitude, title=None):
    return {
        "id": str(vehicle_id),
        "vehicle_id": vehicle_id,
        "lat": latitude,
        "lng": longitude,
        "title": title or f"Veículo {vehicle_id}",
    }


def _layers_of(control, layer_type):
    return [layer for layer in control.layers if isinstance(layer, layer_type)]


def test_map_view_builds_real_map_with_tile_and_marker_layers():
    control = MapView([_marker(1, -27.815, -50.326)]).build()

    assert isinstance(control, fmap.Map)
    assert _layers_of(control, fmap.TileLayer)
    assert _layers_of(control, fmap.MarkerLayer)


def test_map_view_empty_state_keeps_real_map():
    control = MapView().build()

    assert isinstance(control, fmap.Map)
    assert _layers_of(control, fmap.TileLayer)
    assert _layers_of(control, fmap.MarkerLayer)[0].markers == []


def test_map_view_creates_distinct_markers_for_two_vehicles():
    control = MapView([
        _marker(1, -27.815, -50.326, "ABC1234"),
        _marker(3, -27.825, -50.316, "TRKB1234"),
    ]).build()

    markers = _layers_of(control, fmap.MarkerLayer)[0].markers
    assert len(markers) == 2
    assert {marker.data["vehicle_id"] for marker in markers} == {1, 3}


def test_map_view_set_markers_replaces_same_vehicle_without_duplicates():
    view = MapView([_marker(1, -27.815, -50.326, "ABC1234")])
    control = view.build()

    view.set_markers([_marker(1, -27.814, -50.325, "ABC1234")])

    marker_layer = _layers_of(control, fmap.MarkerLayer)[0]
    assert len(marker_layer.markers) == 1
    assert marker_layer.markers[0].coordinates.latitude == -27.814
    assert marker_layer.markers[0].coordinates.longitude == -50.325


def test_map_view_ignores_invalid_marker_coordinates():
    control = MapView([
        _marker(1, 91, -50.326),
        _marker(2, -27.815, "invalid"),
        _marker(3, -27.815, -50.326),
    ]).build()

    markers = _layers_of(control, fmap.MarkerLayer)[0].markers
    assert len(markers) == 1
    assert markers[0].data["vehicle_id"] == 3


def test_application_refresh_map_markers_keeps_map_contract():
    from unittest.mock import MagicMock
    from app.application import DeliveryApp

    app = DeliveryApp.__new__(DeliveryApp)
    app.vehicle_states = {"1": {"vehicle_id": 1, "latitude": -27.815, "longitude": -50.326}}
    app.map_control = MapView().build()

    DeliveryApp._refresh_map_markers(app)

    marker_layer = _layers_of(app.map_control, fmap.MarkerLayer)[0]
    assert len(marker_layer.markers) == 1
    assert marker_layer.markers[0].data["vehicle_id"] == 1