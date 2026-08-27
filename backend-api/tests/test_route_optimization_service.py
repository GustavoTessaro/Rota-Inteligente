import json
import types

from app.services import google_route_optimization_service as service_module
from app.services.google_route_optimization_service import GoogleRouteOptimizationService


def test_token_fallback_no_file(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    assert svc._get_access_token() is None


def test_optimize_raises_without_endpoint(monkeypatch, tmp_path):
    sa = {
        "client_email": "test@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB...\n-----END PRIVATE KEY-----\n",
    }
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps(sa))

    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: types.SimpleNamespace(
            google_route_optimization_service_account_file=None,
            google_route_optimization_endpoint=None,
            google_route_optimization_scope="https://www.googleapis.com/auth/cloud-platform",
            google_maps_api_key=None,
        ),
    )

    svc = GoogleRouteOptimizationService(service_account_file=str(sa_file), endpoint=None)
    try:
        svc.optimize_route({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}, [{"lat":0.1, "lng":0.1}])
        assert False, "Expected RuntimeError when no API key is configured"
    except RuntimeError:
        pass


def test_optimize_calls_endpoint(monkeypatch, tmp_path):
    # create fake service account file
    sa = {
        "client_email": "test@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB...\n-----END PRIVATE KEY-----\n",
    }
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps(sa))

    class DummyResponse:
        def __init__(self, json_data):
            self._json = json_data
            self.status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return self._json

    def fake_post(url, json=None, headers=None, timeout=None, data=None):
        # respond to token exchange and to optimization endpoint
        if 'oauth2.googleapis.com' in url:
            return DummyResponse({'access_token': 'ya29.fake', 'expires_in': 3600})
        return DummyResponse({'optimized_order': [0], 'ordered_waypoints': json.get('waypoints', [])})

    monkeypatch.setattr('httpx.post', fake_post)

    class DummyCreds:
        def __init__(self):
            self.token = None
            self.expiry = None

        def refresh(self, req):
            self.token = 'ya29.fake'
            from datetime import datetime, timedelta
            self.expiry = datetime.utcnow() + timedelta(seconds=3600)

    # Monkeypatch google-auth credential loading if available in the service module
    try:
        import app.services.google_route_optimization_service as service_mod
        monkeypatch.setattr(service_mod.service_account.Credentials, 'from_service_account_file', lambda path, scopes=None: DummyCreds())
    except Exception:
        pass

    svc = GoogleRouteOptimizationService(service_account_file=str(sa_file), endpoint='https://example.com/opt')
    res = svc.optimize_route({'lat':0,'lng':0},{'lat':1,'lng':1}, [{'lat':0.1,'lng':0.1}])
    assert 'optimized_order' in res


def test_objective_selects_duration_or_distance_without_extra_permutations(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    results = {
        (0, 1): {"distanceMeters": 100, "duration": "20s", "polyline": {"encodedPolyline": "short"}},
        (1, 0): {"distanceMeters": 200, "duration": "10s", "polyline": {"encodedPolyline": "fast"}},
    }

    monkeypatch.setattr(
        svc,
        "_compute_routes_response",
        lambda origin, destination, waypoints: {"routes": [results[tuple(point["id"] for point in waypoints)] ]},
    )
    origin = {"lat": 0, "lng": 0}
    destination = {"lat": 1, "lng": 1}
    waypoints = [{"id": 0, "lat": 0.1, "lng": 0.1}, {"id": 1, "lat": 0.2, "lng": 0.2}]

    fastest = svc.optimize_route(origin, destination, waypoints, objective="MAIS_RAPIDA")
    shortest = svc.optimize_route(origin, destination, waypoints, objective="MAIS_CURTA")

    assert fastest["optimized_order"] == [1, 0]
    assert shortest["optimized_order"] == [0, 1]

 