import json
import types
from pathlib import Path

from app.services import google_route_optimization_service as service_module
from app.services.google_route_optimization_service import GoogleRouteOptimizationService


def test_service_account_path_is_resolved_from_repo_root(monkeypatch):
    rel = Path("backend-api") / "secrets" / "gmp-demo-project-938388767-2b753ed1c56d.json"
    svc = GoogleRouteOptimizationService(service_account_file=str(rel), endpoint=None)
    assert Path(svc.sa_file).is_file()


def test_rebuild_visit_order_accepts_explicit_zero_shipment_index(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    waypoints = [{"label": "shipment-0"}, {"label": "shipment-1"}, {"label": "shipment-2"}]
    visits = [{"shipmentIndex": 0, "shipmentLabel": "shipment-0"}, {"shipmentIndex": 1, "shipmentLabel": "shipment-1"}, {"shipmentIndex": 2, "shipmentLabel": "shipment-2"}]
    assert svc._rebuild_visit_order(visits, waypoints) == [0, 1, 2]


def test_rebuild_visit_order_uses_label_when_index_is_omitted(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    waypoints = [{"label": "shipment-0"}, {"label": "shipment-1"}, {"label": "shipment-2"}]
    visits = [{"shipmentLabel": "shipment-0"}, {"shipmentLabel": "shipment-1"}, {"shipmentLabel": "shipment-2"}]
    assert svc._rebuild_visit_order(visits, waypoints) == [0, 1, 2]


def test_rebuild_visit_order_rejects_unknown_label(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    waypoints = [{"label": "shipment-0"}, {"label": "shipment-1"}]
    visits = [{"shipmentLabel": "shipment-99"}]
    try:
        svc._rebuild_visit_order(visits, waypoints)
        assert False
    except RuntimeError as exc:
        assert "unknown shipmentLabel" in str(exc)


def test_rebuild_visit_order_rejects_duplicate_labels(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    waypoints = [{"label": "shipment-0"}, {"label": "shipment-0"}]
    try:
        svc._rebuild_visit_order([], waypoints)
        assert False
    except RuntimeError as exc:
        assert "duplicate shipment labels" in str(exc)


def test_rebuild_visit_order_rejects_duplicate_indexes(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    waypoints = [{"label": "shipment-0"}, {"label": "shipment-1"}]
    visits = [{"shipmentIndex": 0}, {"shipmentIndex": 0}]
    try:
        svc._rebuild_visit_order(visits, waypoints)
        assert False
    except RuntimeError as exc:
        assert "duplicate shipmentIndex" in str(exc)


def test_rebuild_visit_order_rejects_incomplete_sequence(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    waypoints = [{"label": "shipment-0"}, {"label": "shipment-1"}, {"label": "shipment-2"}]
    visits = [{"shipmentIndex": 0}, {"shipmentIndex": 2}]
    try:
        svc._rebuild_visit_order(visits, waypoints)
        assert False
    except RuntimeError as exc:
        assert "incomplete visit sequence" in str(exc)


def test_rebuild_visit_order_rejects_skipped_shipments(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    waypoints = [{"label": "shipment-0"}, {"label": "shipment-1"}]
    visits = [{"shipmentIndex": 0}, {"shipmentIndex": 1}]
    try:
        svc._rebuild_visit_order(visits, waypoints, skipped_shipments=[1])
        assert False
    except RuntimeError as exc:
        assert "skipped shipments" in str(exc)


def test_token_fallback_no_file(monkeypatch):
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

    monkeypatch.setattr(svc, "_get_access_token", lambda: "token")
    svc.project_id = "project"
    monkeypatch.setattr(svc, "_optimize_tours_order", lambda origin, destination, points, objective: [1, 0] if objective == "MAIS_RAPIDA" else [0, 1])
    monkeypatch.setattr(svc, "_compute_routes_response", lambda origin, destination, points: {"routes": [results[tuple(point["id"] for point in points)]]})
    origin = {"lat": 0, "lng": 0}
    destination = {"lat": 1, "lng": 1}
    waypoints = [{"id": 0, "lat": 0.1, "lng": 0.1}, {"id": 1, "lat": 0.2, "lng": 0.2}]

    fastest = svc.optimize_route(origin, destination, waypoints, objective="MAIS_RAPIDA")
    shortest = svc.optimize_route(origin, destination, waypoints, objective="MAIS_CURTA")

    assert fastest["optimized_order"] == [1, 0]
    assert shortest["optimized_order"] == [0, 1]


def test_optimize_tours_handles_five_waypoints_and_preserves_evaluation_bundle(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file="service.json", endpoint=None)
    svc.project_id = "project"
    svc._get_access_token = lambda: "token"
    requests = []

    class Response:
        def __init__(self, order):
            self.order = order

        def raise_for_status(self):
            return None

        def json(self):
            return {"routes": [{"visits": [{"shipmentIndex": index} for index in self.order]}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        requests.append(json)
        return Response([4, 2, 0, 3, 1])

    monkeypatch.setattr(service_module.httpx, "post", fake_post)
    monkeypatch.setattr(
        svc,
        "_compute_routes_response",
        lambda origin, destination, points: {
            "routes": [{
                "distanceMeters": 10000,
                "duration": "1215s",
                "polyline": {"encodedPolyline": "bundle"},
            }]
        },
    )
    points = [{"id": index, "lat": index / 10, "lng": index / 10} for index in range(5)]

    result = svc.optimize_route({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}, points, objective="MAIS_RAPIDA")

    assert result["optimized_order"] != [0, 1, 2, 3, 4]
    assert result["optimized_order"] == [4, 2, 0, 3, 1]
    assert result["distance_meters"] == 10000
    assert result["duration_seconds"] == 1215
    assert result["encoded_polyline"] == "bundle"
    assert requests[0]["model"]["vehicles"][0]["costPerTraveledHour"] == 1.0
    assert "costPerKilometer" not in requests[0]["model"]["vehicles"][0]


def test_optimize_tours_uses_distance_cost_for_shortest(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file="service.json", endpoint=None)
    svc.project_id = "project"
    svc._get_access_token = lambda: "token"
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"routes": [{"visits": [{"shipmentIndex": 0}, {"shipmentIndex": 1}]}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["body"] = json
        captured["url"] = url
        return Response()

    monkeypatch.setattr(service_module.httpx, "post", fake_post)
    monkeypatch.setattr(svc, "_compute_routes_response", lambda origin, destination, points: {"routes": [{"distanceMeters": 1, "duration": "1s"}]})
    svc.optimize_route({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}, [{"lat": 0.1, "lng": 0.1}, {"lat": 0.2, "lng": 0.2}], objective="MAIS_CURTA")

    vehicle = captured["body"]["model"]["vehicles"][0]
    assert vehicle["costPerKilometer"] == 1.0
    assert "costPerHour" not in vehicle
    assert captured["url"] == "https://routeoptimization.googleapis.com/v1/projects/project:optimizeTours"


def test_optimize_tours_uses_project_level_endpoint_without_location(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file="service.json", endpoint=None)
    svc.project_id = "project"
    svc.location = "us-central1"
    svc._get_access_token = lambda: "token"
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"routes": [{"visits": [{"shipmentIndex": 0}, {"shipmentIndex": 1}]}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        return Response()

    monkeypatch.setattr(service_module.httpx, "post", fake_post)
    monkeypatch.setattr(svc, "_compute_routes_response", lambda origin, destination, points: {"routes": [{"distanceMeters": 1, "duration": "1s"}]})

    svc.optimize_route({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}, [{"lat": 0.1, "lng": 0.1}, {"lat": 0.2, "lng": 0.2}], objective="MAIS_CURTA")

    assert captured["url"] == "https://routeoptimization.googleapis.com/v1/projects/project:optimizeTours"
    assert "/locations/" not in captured["url"]


def test_fifteen_second_difference_keeps_each_candidate_bundle_atomic(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file="service.json", endpoint=None)
    svc.project_id = "project"
    svc._get_access_token = lambda: "token"
    monkeypatch.setattr(svc, "_optimize_tours_order", lambda origin, destination, points, objective: [1, 0] if objective == "MAIS_RAPIDA" else [0, 1])

    candidates = {
        (0, 1): (10000, "1215s", "polyline-short"),
        (1, 0): (10400, "1200s", "polyline-fast"),
    }
    monkeypatch.setattr(
        svc,
        "_compute_routes_response",
        lambda origin, destination, points: {
            "routes": [{
                "distanceMeters": candidates[tuple(point["id"] for point in points)][0],
                "duration": candidates[tuple(point["id"] for point in points)][1],
                "polyline": {"encodedPolyline": candidates[tuple(point["id"] for point in points)][2]},
            }]
        },
    )
    points = [{"id": 0, "lat": 0.1, "lng": 0.1}, {"id": 1, "lat": 0.2, "lng": 0.2}]

    fastest = svc.optimize_route({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}, points, objective="MAIS_RAPIDA")
    shortest = svc.optimize_route({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}, points, objective="MAIS_CURTA")

    assert fastest["optimized_order"] == [1, 0]
    assert fastest["distance_meters"] == 10400
    assert fastest["duration_seconds"] == 1200
    assert fastest["encoded_polyline"] == "polyline-fast"
    assert shortest["optimized_order"] == [0, 1]
    assert shortest["distance_meters"] == 10000
    assert shortest["duration_seconds"] == 1215
    assert shortest["encoded_polyline"] == "polyline-short"


def test_fallback_is_explicit_and_does_not_claim_optimization(monkeypatch):
    from app.services import google_maps_service as maps_module
    monkeypatch.setattr(maps_module.settings, "use_google_route_optimization", False)
    from app.services.google_maps_service import GoogleMapsService

    result = GoogleMapsService().optimize_route(
        origin={"lat": 0, "lng": 0},
        destination={"lat": 1, "lng": 1},
        waypoints=[{"id": 0, "lat": 0.1, "lng": 0.1}, {"id": 1, "lat": 0.2, "lng": 0.2}, {"id": 2, "lat": 0.3, "lng": 0.3}, {"id": 3, "lat": 0.4, "lng": 0.4}, {"id": 4, "lat": 0.5, "lng": 0.5}],
    )

    assert result["optimized_order"] == [0, 1, 2, 3, 4]
    assert result["provider"] == "FALLBACK"
    assert result["optimized"] is False

 