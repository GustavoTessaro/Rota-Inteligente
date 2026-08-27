import flet as ft
import flet_map as fmap
import pytest

import app.map_view as map_view_module
from app.map_view import MapView


@pytest.fixture(autouse=True)
def configured_maptiler_key(monkeypatch):
    monkeypatch.setattr(map_view_module, "MAPTILER_API_KEY", "test-only-value")


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
    tile_layers = _layers_of(control, fmap.TileLayer)
    assert tile_layers
    assert tile_layers[0].url_template == (
        "https://api.maptiler.com/maps/streets-v4/"
        "{z}/{x}/{y}.png?key=test-only-value"
    )
    assert _layers_of(control, fmap.MarkerLayer)


def test_map_view_requires_maptiler_configuration(monkeypatch):
    monkeypatch.setattr(map_view_module, "MAPTILER_API_KEY", "")

    with pytest.raises(RuntimeError, match="MAPTILER_API_KEY"):
        MapView().build()


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


def test_application_removes_stale_vehicle_state_and_ignores_invalid_timestamp():
    from datetime import datetime, timedelta, timezone
    from app.application import DeliveryApp

    app = DeliveryApp.__new__(DeliveryApp)
    app.vehicle_states = {
        "old": {
            "vehicle_id": 1,
            "latitude": -27.815,
            "longitude": -50.326,
            "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=46)).isoformat(),
        },
        "invalid": {
            "vehicle_id": 2,
            "latitude": -27.815,
            "longitude": -50.326,
            "timestamp": "not-a-timestamp",
        },
        "recent": {
            "vehicle_id": 3,
            "latitude": -27.815,
            "longitude": -50.326,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    app._refresh_map_markers = lambda: None

    assert DeliveryApp._remove_stale_vehicle_states(app) is True
    assert set(app.vehicle_states) == {"invalid", "recent"}


def test_map_view_refresh_preserves_map_and_tile_layers():
    view = MapView()
    control = view.build()
    original_layers = control.layers

    view.set_markers([_marker(1, -27.815, -50.326, "ABC1234")])
    view.set_markers([])

    assert view._control is control
    assert control.layers is original_layers
    assert isinstance(control.layers[0], fmap.TileLayer)
    assert isinstance(control.layers[1], fmap.SimpleAttribution)
    assert isinstance(control.layers[2], fmap.MarkerLayer)


def test_dashboard_map_is_created_once_and_reused_for_refreshes():
    from unittest.mock import MagicMock, patch
    from app.application import DeliveryApp

    app = DeliveryApp.__new__(DeliveryApp)
    app.map_control = None
    app.dashboard_map_view = None
    app.vehicle_states = {}

    with patch("app.application.MapView") as map_view_class:
        map_view = map_view_class.return_value
        map_view.build.return_value = object()
        DeliveryApp._ensure_dashboard_map(app, [])
        first_control = app.map_control
        DeliveryApp._ensure_dashboard_map(app, [])

    map_view_class.assert_called_once()
    map_view.build.assert_called_once()
    assert app.map_control is first_control
    assert map_view.set_markers.call_count == 1


def test_dashboard_refresh_updates_data_without_rebuilding_visible_dashboard():
    from unittest.mock import MagicMock, patch
    from app.application import DeliveryApp

    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "ADMIN"}
    app.dashboard_active = True
    app.dashboard_screen_visible = True
    app.dashboard_initialized = True
    app.dashboard_data = {"entregas_hoje": 1}
    app.content = MagicMock()
    app.content.controls = [object()]
    app.api = MagicMock()
    app.api.request.return_value = {"entregas_hoje": 2}
    app._update_dashboard_controls = MagicMock()

    with patch.object(app, "dashboard_view") as dashboard_view:
        DeliveryApp._refresh_dashboard(app)

    dashboard_view.assert_not_called()
    app._update_dashboard_controls.assert_called_once_with({"entregas_hoje": 2})
    assert app.dashboard_data["entregas_hoje"] == 2


def test_dashboard_graph_rows_use_finite_panel_dimensions_without_vertical_expand():
    from unittest.mock import MagicMock
    from app.application import DeliveryApp

    app = DeliveryApp(MagicMock())
    app.user = {"perfil": "ADMIN"}
    app.api.request = MagicMock(return_value={})
    app.dashboard_view()

    graph_rows = app.content.controls[2:4]
    assert len(graph_rows) == 2
    for row_container in graph_rows:
        assert isinstance(row_container, ft.Container)
        assert isinstance(row_container.content, ft.Row)
        assert row_container.content.wrap is True
        assert all(
            isinstance(panel, ft.Container)
            and panel.width == 360
            and panel.height == 180
            for panel in row_container.content.controls
        )
        assert all(panel.expand is None for panel in row_container.content.controls)


def test_dashboard_keeps_graphs_before_map_and_attached_text_removed():
    from unittest.mock import MagicMock
    from app.application import DeliveryApp

    app = DeliveryApp(MagicMock())
    app.user = {"perfil": "ADMIN"}
    app.api.request = MagicMock(return_value={})
    app.dashboard_view()

    text_values = [control.value for control in app.content.controls if isinstance(control, ft.Text)]
    assert "ATTACHED DASHBOARD CONTENT TEST" not in text_values
    assert isinstance(app.content.controls[4], ft.Container)
    assert app.map_control is app.content.controls[4].content.controls[-1]


def test_dashboard_last_section_uses_finite_panels_without_expand():
    from unittest.mock import MagicMock
    from app.application import DeliveryApp

    app = DeliveryApp(MagicMock())
    app.user = {"perfil": "ADMIN"}
    app.api.request = MagicMock(return_value={})
    app.dashboard_view()

    last_section = app.content.controls[5]
    panels = last_section.content.controls
    assert len(panels) == 2
    assert all(panel.expand is None for panel in panels)
    assert all(panel.width == 360 and panel.height == 180 for panel in panels)