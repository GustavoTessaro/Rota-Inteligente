from __future__ import annotations

from typing import Any


TERMINAL_TRACKING_STATUSES = {"PAUSADA", "CONCLUIDA", "FINALIZADA", "CANCELADA"}


def parse_position_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        print("[TRACKING_ADMIN] mensagem ignorada motivo=mensagem não é objeto")
        return None
    if message.get("type") != "rota_posicao":
        print(f"[TRACKING_ADMIN] mensagem ignorada motivo=type inválido type={message.get('type')}")
        return None

    payload = message.get("payload")
    if not isinstance(payload, dict):
        print("[TRACKING_ADMIN] mensagem ignorada motivo=payload inválido")
        return None

    vehicle_id = payload.get("veiculo_id")
    if vehicle_id in (None, ""):
        print("[TRACKING_ADMIN] mensagem ignorada motivo=veiculo_id ausente")
        return None

    try:
        latitude = float(payload.get("latitude"))
        longitude = float(payload.get("longitude"))
    except (TypeError, ValueError):
        print("[TRACKING_ADMIN] mensagem ignorada motivo=latitude_longitude inválidas")
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        print("[TRACKING_ADMIN] mensagem ignorada motivo=latitude_longitude fora do intervalo")
        return None

    speed = None
    heading = None
    try:
        if payload.get("velocidade") is not None:
            speed = float(payload.get("velocidade"))
        if payload.get("heading") is not None:
            heading = float(payload.get("heading"))
    except (TypeError, ValueError):
        print("[TRACKING_ADMIN] mensagem ignorada motivo=velocidade_heading inválidos")
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
    print(f"[TRACKING_ADMIN] mensagem recebida type={message.get('type') if isinstance(message, dict) else None}")
    if isinstance(message, dict) and message.get("type") == "rota_status":
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return existing
        vehicle_id = payload.get("veiculo_id")
        if payload.get("status") not in TERMINAL_TRACKING_STATUSES or vehicle_id in (None, ""):
            return existing
        updated = dict(existing)
        updated.pop(str(vehicle_id), None)
        return updated
    parsed = parse_position_message(message)
    if not parsed:
        return existing

    updated = dict(existing)
    updated[parsed["id"]] = {**updated.get(parsed["id"], {}), **parsed}
    print(
        f"[TRACKING_ADMIN] rota={parsed.get('route_id')} veiculo={parsed.get('vehicle_id')} "
        f"lat={parsed.get('latitude')} lon={parsed.get('longitude')}"
    )
    print(f"[TRACKING_ADMIN] marker atualizado veiculo={parsed['vehicle_id']}")
    return updated


def build_marker(vehicle_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": vehicle_state.get("id"),
        "vehicle_id": vehicle_state.get("vehicle_id"),
        "lat": vehicle_state.get("latitude"),
        "lng": vehicle_state.get("longitude"),
        "title": vehicle_state.get("title") or f"Veículo {vehicle_state.get('vehicle_id')}",
        "speed": vehicle_state.get("speed"),
        "heading": vehicle_state.get("heading"),
        "timestamp": vehicle_state.get("timestamp"),
    }
