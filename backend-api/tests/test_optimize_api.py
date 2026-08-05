from fastapi.testclient import TestClient
from app.main import app


def test_optimize_endpoint(monkeypatch):
    class FakeSvc:
        def optimize_route(self, origin, destination, waypoints, vehicle_constraints, time_windows):
            return {
                "optimized_order": [1, 0],
                "ordered_waypoints": [waypoints[1], waypoints[0]] if waypoints else [],
                "distance_meters": 2000,
                "duration_seconds": 600,
                "encoded_polyline": "abc123",
            }

    # override dependency used by the router
    from app import api_maps
    app.dependency_overrides[api_maps.get_google_maps_service] = lambda: FakeSvc()
    client = TestClient(app)
    payload = {"origin": {"lat": 0, "lng": 0}, "destination": {"lat": 1, "lng": 1}, "waypoints": [{"lat": 0.1, "lng": 0.1}, {"lat": 0.2, "lng": 0.2}]}
    res = client.post("/api/maps/optimize", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["optimized_order"] == [1, 0]
    assert data["encoded_polyline"] == "abc123"
    assert data["distance_meters"] == 2000
