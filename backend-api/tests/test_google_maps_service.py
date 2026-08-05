import pytest
import httpx

from app.services.google_maps_service import GoogleMapsService


class MockResponse:
    def __init__(self, json_data=None, status_code=200, raise_on_raise_for_status=None, json_exception=None):
        self._json = json_data or {}
        self.status_code = status_code
        self._raise = raise_on_raise_for_status
        self._json_exc = json_exception

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        if self._json_exc:
            raise self._json_exc
        return self._json


def test_geocode_success(monkeypatch):
    svc = GoogleMapsService(api_key="fake")

    expected = {"results": [{"formatted_address": "Rua Teste, 1"}], "status": "OK"}

    def fake_get(url, params=None, timeout=None):
        assert "geocode" in url
        assert params["address"] == "Rua Teste"
        return MockResponse(json_data=expected)

    monkeypatch.setattr(httpx, "get", fake_get)

    res = svc.geocode("Rua Teste")
    assert res == expected


def test_reverse_geocode_success(monkeypatch):
    svc = GoogleMapsService(api_key="fake")

    expected = {"results": [{"formatted_address": "Praça Exemplo, 1"}], "status": "OK"}

    def fake_get(url, params=None, timeout=None):
        assert "latlng" in params
        return MockResponse(json_data=expected)

    monkeypatch.setattr(httpx, "get", fake_get)

    res = svc.reverse_geocode(-23.5, -46.6)
    assert res == expected


def test_geocode_timeout(monkeypatch):
    svc = GoogleMapsService(api_key="fake")

    def fake_get(url, params=None, timeout=None):
        raise httpx.ReadTimeout("timeout")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(httpx.ReadTimeout):
        svc.geocode("Alguma rua")


def test_directions_success(monkeypatch):
    svc = GoogleMapsService(api_key="fake")

    origin = {"lat": -23.5, "lng": -46.6}
    dest = {"lat": -23.6, "lng": -46.7}
    waypoints = [{"lat": -23.55, "lng": -46.65}]

    expected = {"routes": [{"summary": "Rota A"}], "status": "OK"}

    def fake_post(url, params=None, json=None, headers=None, timeout=None):
        assert ":computeRoutes" in url
        assert json is not None
        # check origin/destination shape
        assert json["origin"]["location"]["latLng"]["latitude"] == origin["lat"]
        return MockResponse(json_data=expected)

    monkeypatch.setattr(httpx, "post", fake_post)

    res = svc.directions(origin, dest, waypoints)
    assert res == expected


def test_directions_http_error(monkeypatch):
    svc = GoogleMapsService(api_key="fake")

    def fake_post(url, params=None, json=None, headers=None, timeout=None):
        return MockResponse(raise_on_raise_for_status=httpx.HTTPError("bad"))

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(httpx.HTTPError):
        svc.directions({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1})


def test_directions_invalid_json(monkeypatch):
    svc = GoogleMapsService(api_key="fake")

    def fake_post(url, params=None, json=None, headers=None, timeout=None):
        return MockResponse(json_exception=ValueError("Invalid JSON"))

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(ValueError):
        svc.directions({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1})


def test_optimize_stub_returns_order():
    svc = GoogleMapsService(api_key="fake")
    waypoints = [{"lat": -23.5, "lng": -46.6}, {"lat": -23.6, "lng": -46.7}]
    res = svc.optimize_route(waypoints, vehicle_count=1)
    assert "optimized_order" in res
    assert res["optimized_order"] == [0, 1]
    assert res["waypoints"] == waypoints
