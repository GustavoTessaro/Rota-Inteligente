from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import flet_geolocator as geolocator_api

from .driver_location_tracking import LocationSample


class GeolocationPermissionDenied(RuntimeError):
    pass


class GeolocationServiceUnavailable(RuntimeError):
    pass


class GeolocationProvider:
    def __init__(self, geolocator: Any | None = None):
        self.control = geolocator or geolocator_api.Geolocator()

    def get_position(self) -> LocationSample | None:
        print("[TRACKING] solicitando posição GPS")
        if not self.control.is_location_service_enabled():
            raise GeolocationServiceUnavailable("serviço de localização desabilitado")

        permission = self._permission_value(self.control.get_permission_status())
        if permission not in {"whileInUse", "always"}:
            permission = self._permission_value(self.control.request_permission())
        if permission not in {"whileInUse", "always"}:
            raise GeolocationPermissionDenied("permissão de localização negada")

        position = self.control.get_current_position(
            accuracy=geolocator_api.GeolocatorPositionAccuracy.HIGH
        )
        if position is None or position.latitude is None or position.longitude is None:
            print("[TRACKING] GPS_ACQUISITION_SUCCESS=false posição vazia")
            return None
        print(
            "[TRACKING] GPS_ACQUISITION_SUCCESS=true "
            f"posição obtida lat={position.latitude} lon={position.longitude} "
            f"accuracy={position.accuracy}"
        )
        return LocationSample(
            latitude=position.latitude,
            longitude=position.longitude,
            accuracy=position.accuracy,
            speed=position.speed,
            heading=position.heading,
            timestamp=self._timestamp(position.timestamp),
        )

    @staticmethod
    def _permission_value(permission: Any) -> str | None:
        if permission is None:
            return None
        return getattr(permission, "value", permission)

    @staticmethod
    def _timestamp(value: Any) -> str | None:
        if value is None or isinstance(value, str):
            return value
        try:
            seconds = float(value)
            if seconds > 100_000_000_000:
                seconds /= 1000
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            return None
