from datetime import datetime
from types import SimpleNamespace

import pytest

from app.geolocation_provider import (
    GeolocationPermissionDenied,
    GeolocationProvider,
    GeolocationServiceUnavailable,
)


class FakeGeolocator:
    def __init__(self, enabled=True, permission="whileInUse", position=None, error=None):
        self.enabled = enabled
        self.permission = permission
        self.position = position
        self.error = error
        self.permission_requests = 0
        self.position_requests = 0

    def is_location_service_enabled(self):
        return self.enabled

    def get_permission_status(self):
        return SimpleNamespace(value=self.permission)

    def request_permission(self):
        self.permission_requests += 1
        return SimpleNamespace(value=self.permission)

    def get_current_position(self, **kwargs):
        self.position_requests += 1
        if self.error:
            raise self.error
        return self.position


def valid_position():
    return SimpleNamespace(
        latitude=-27.815,
        longitude=-50.326,
        accuracy=10,
        speed=32,
        heading=90,
        timestamp=1_724_550_000_000,
    )


def test_permission_already_granted_reads_position():
    geolocator = FakeGeolocator(position=valid_position())
    provider = GeolocationProvider(geolocator)

    result = provider.get_position()

    assert result.latitude == -27.815
    assert result.longitude == -50.326
    assert result.accuracy == 10
    assert geolocator.permission_requests == 0
    assert geolocator.position_requests == 1


def test_denied_permission_does_not_access_position():
    geolocator = FakeGeolocator(permission="denied", position=valid_position())
    provider = GeolocationProvider(geolocator)

    with pytest.raises(GeolocationPermissionDenied):
        provider.get_position()

    assert geolocator.position_requests == 0


def test_disabled_location_service_is_reported():
    geolocator = FakeGeolocator(enabled=False, position=valid_position())
    provider = GeolocationProvider(geolocator)

    with pytest.raises(GeolocationServiceUnavailable):
        provider.get_position()

    assert geolocator.position_requests == 0


def test_position_fields_are_converted_to_location_sample():
    provider = GeolocationProvider(FakeGeolocator(position=valid_position()))

    result = provider.get_position()

    assert result.latitude == -27.815
    assert result.longitude == -50.326
    assert result.accuracy == 10
    assert result.speed == 32
    assert result.heading == 90
    assert isinstance(result.timestamp, str)


def test_missing_position_is_returned_as_none():
    provider = GeolocationProvider(FakeGeolocator(position=None))

    assert provider.get_position() is None


def test_geolocator_error_is_wrapped():
    provider = GeolocationProvider(FakeGeolocator(error=RuntimeError("native failure")))

    with pytest.raises(RuntimeError, match="native failure"):
        provider.get_position()


def test_request_permission_allows_position_when_granted():
    geolocator = FakeGeolocator(permission="whileInUse", position=valid_position())
    provider = GeolocationProvider(geolocator)

    assert provider.get_position() is not None
    assert geolocator.permission_requests == 0
