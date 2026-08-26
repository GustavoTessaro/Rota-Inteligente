from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from threading import Event, Lock, Thread, current_thread
from typing import Callable


@dataclass
class LocationSample:
    latitude: float
    longitude: float
    accuracy: float | None = None
    speed: float | None = None
    heading: float | None = None
    timestamp: datetime | str | None = None


class DriverLocationTracking:
    def __init__(
        self,
        location_provider: Callable[[], LocationSample | None],
        publish_position: Callable[[int, dict], None],
        interval: float = 15.0,
        max_accuracy: float = 100.0,
        provider_name: str = "flet-geolocator",
        on_error: Callable[[Exception], None] | None = None,
    ):
        self.location_provider = location_provider
        self.publish_position = publish_position
        self.interval = interval
        self.max_accuracy = max_accuracy
        self.provider_name = provider_name
        self.on_error = on_error
        self.route_id: int | None = None
        self.vehicle_id: int | None = None
        self._active = False
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self, route_id: int | None, route_status: str, vehicle_id: int | None) -> bool:
        if route_id is None:
            raise ValueError("route_id é obrigatório")
        if route_status != "EM_EXECUCAO":
            raise ValueError("tracking só inicia em rota EM_EXECUCAO")
        if vehicle_id is None:
            raise ValueError("veiculo_id é obrigatório")

        with self._lock:
            if self._active:
                return False
            self.route_id = route_id
            self.vehicle_id = vehicle_id
            self._stop_event.clear()
            self._active = True
            self._thread = Thread(target=self._run, daemon=True)
            self._thread.start()
        return True

    def stop(self) -> None:
        with self._lock:
            self._active = False
            self._stop_event.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread is not current_thread():
            thread.join(timeout=1.0)

    def update_route_status(self, route_status: str) -> None:
        if route_status != "EM_EXECUCAO":
            self.stop()

    def publish_sample(self, sample: LocationSample | None) -> bool:
        if not self.active or self.route_id is None or not self._is_valid(sample):
            return False
        values = asdict(sample)
        timestamp = values.pop("timestamp")
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()
        elif timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "latitude": values["latitude"],
            "longitude": values["longitude"],
            "timestamp": timestamp,
            "provider": self.provider_name,
        }
        optional_fields = {
            "velocidade": values.get("speed"),
            "heading": values.get("heading"),
            "accuracy": values.get("accuracy"),
        }
        payload.update({key: value for key, value in optional_fields.items() if value is not None})
        try:
            self.publish_position(self.route_id, payload)
        except Exception as exc:
            if self.on_error is not None:
                self.on_error(exc)
            return False
        return True

    def _run(self) -> None:
        while self.active and not self._stop_event.is_set():
            try:
                self.publish_sample(self.location_provider())
            except Exception as exc:
                if self.on_error is not None:
                    self.on_error(exc)
            self._stop_event.wait(self.interval)

    def _is_valid(self, sample: LocationSample | None) -> bool:
        if sample is None:
            return False
        try:
            latitude = float(sample.latitude)
            longitude = float(sample.longitude)
        except (TypeError, ValueError):
            return False
        if not (isfinite(latitude) and isfinite(longitude)):
            return False
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return False
        if sample.accuracy is None:
            return False
        try:
            accuracy = float(sample.accuracy)
        except (TypeError, ValueError):
            return False
        return isfinite(accuracy) and 0 <= accuracy <= self.max_accuracy
