from __future__ import annotations

from typing import Any


def parse_position_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    if message.get("type") != "rota_posicao":
        return None

    payload = message.get("payload")
    if not isinstance(payload, dict):
        return None

    vehicle_id = payload.get("veiculo_id")
    if vehicle_id in (None, ""):
        return None

    try:
        latitude = float(payload.get("latitude"))
        longitude = float(payload.get("longitude"))
    except (TypeError, ValueError):
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    speed = None
    heading = None
    try:
        if payload.get("velocidade") is not None:
            speed = float(payload.get("velocidade"))
        if payload.get("heading") is not None:
            heading = float(payload.get("heading"))
    except (TypeError, ValueError):
        speed = None
        heading = None

    vehicle_key = str(vehicle_id)
    return {
        "id": vehicle_key,
        "vehicle_id": vehicle_id,
        "latitude": latitude,
        "longitude": longitude,
        "speed": speed,
        "heading": heading,
        "timestamp": payload.get("timestamp"),
        "route_id": payload.get("rota_id"),
        "provider": payload.get("provider"),
        "title": f"Veículo {vehicle_id}",
    }


def update_vehicle_state(existing: dict[str, dict[str, Any]], message: Any) -> dict[str, dict[str, Any]]:
    parsed = parse_position_message(message)
    if not parsed:
        return existing

    updated = dict(existing)
    updated[parsed["id"]] = {**updated.get(parsed["id"], {}), **parsed}
    return updated


def build_marker(vehicle_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": vehicle_state.get("id"),
        "lat": vehicle_state.get("latitude"),
        "lng": vehicle_state.get("longitude"),
        "title": vehicle_state.get("title") or f"Veículo {vehicle_state.get('vehicle_id')}",
        "speed": vehicle_state.get("speed"),
        "heading": vehicle_state.get("heading"),
        "timestamp": vehicle_state.get("timestamp"),
    }
