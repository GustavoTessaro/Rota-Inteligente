import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "app" / "tracking_client.py"
TRACKING_SPEC = importlib.util.spec_from_file_location("frontend_tracking_client", MODULE_PATH)
TRACKING_CLIENT = importlib.util.module_from_spec(TRACKING_SPEC)
assert TRACKING_SPEC.loader is not None
TRACKING_SPEC.loader.exec_module(TRACKING_CLIENT)

CONFIG_PATH = ROOT / "app" / "config.py"
CONFIG_SPEC = importlib.util.spec_from_file_location("frontend_config", CONFIG_PATH)
CONFIG_MODULE = importlib.util.module_from_spec(CONFIG_SPEC)
assert CONFIG_SPEC.loader is not None
CONFIG_SPEC.loader.exec_module(CONFIG_MODULE)

build_marker = TRACKING_CLIENT.build_marker
parse_position_message = TRACKING_CLIENT.parse_position_message
update_vehicle_state = TRACKING_CLIENT.update_vehicle_state
build_tracking_ws_url = CONFIG_MODULE.build_tracking_ws_url


def test_parse_position_message_accepts_valid_payload():
    message = {
        "type": "rota_posicao",
        "payload": {
            "veiculo_id": 7,
            "latitude": "-23.55",
            "longitude": "-46.63",
            "velocidade": "12.5",
            "heading": "90",
            "timestamp": "2026-08-07T10:00:00",
            "rota_id": 1,
            "provider": "gps",
        },
    }

    parsed = parse_position_message(message)

    assert parsed is not None
    assert parsed["vehicle_id"] == 7
    assert parsed["latitude"] == -23.55
    assert parsed["longitude"] == -46.63
    assert parsed["speed"] == 12.5
    assert parsed["heading"] == 90.0


def test_parse_position_message_rejects_invalid_payload():
    assert parse_position_message({"type": "outro", "payload": {}}) is None
    assert parse_position_message({"type": "rota_posicao", "payload": {"veiculo_id": None, "latitude": "1", "longitude": "2"}}) is None
    assert parse_position_message({"type": "rota_posicao", "payload": {"veiculo_id": 1, "latitude": "91", "longitude": "2"}}) is None


def test_update_vehicle_state_prevents_duplicates_and_updates_existing():
    state = {}
    first = update_vehicle_state(state, {"type": "rota_posicao", "payload": {"veiculo_id": 3, "latitude": "-1", "longitude": "-2", "velocidade": "10"}})
    second = update_vehicle_state(first, {"type": "rota_posicao", "payload": {"veiculo_id": 3, "latitude": "-3", "longitude": "-4", "velocidade": "20"}})

    assert len(second) == 1
    assert second["3"]["latitude"] == -3
    assert second["3"]["speed"] == 20.0


def test_route_status_removes_vehicle_for_terminal_statuses():
    state = {"3": {"vehicle_id": 3, "latitude": -1, "longitude": -2}}

    for status in ("PAUSADA", "CONCLUIDA", "FINALIZADA", "CANCELADA"):
        result = update_vehicle_state(
            state,
            {"type": "rota_status", "payload": {"veiculo_id": 3, "status": status}},
        )
        assert result == {}


def test_route_status_execution_and_unknown_vehicle_are_idempotent():
    state = {"3": {"vehicle_id": 3, "latitude": -1, "longitude": -2}}

    assert update_vehicle_state(
        state,
        {"type": "rota_status", "payload": {"veiculo_id": 3, "status": "EM_EXECUCAO"}},
    ) == state
    assert update_vehicle_state(
        state,
        {"type": "rota_status", "payload": {"veiculo_id": 99, "status": "PAUSADA"}},
    ) == state


def test_build_marker_uses_vehicle_state_fields():
    marker = build_marker({"id": "5", "vehicle_id": 5, "latitude": -1, "longitude": -2, "speed": 7.5, "heading": 180, "timestamp": "abc"})

    assert marker["id"] == "5"
    assert marker["lat"] == -1
    assert marker["lng"] == -2
    assert marker["speed"] == 7.5
    assert marker["heading"] == 180


def test_build_tracking_ws_url_uses_api_base_url():
    assert build_tracking_ws_url("http://127.0.0.1:8000/api") == "ws://127.0.0.1:8000/ws/tracking"
    assert build_tracking_ws_url("https://example.com/api") == "wss://example.com/ws/tracking"
