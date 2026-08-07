from app.services.google_route_optimization_service import GoogleRouteOptimizationService


def test_google_route_service_returns_real_route_metadata():
    service = GoogleRouteOptimizationService()
    origin = {"lat": -23.55052, "lng": -46.633308}
    destination = {"lat": -23.5615, "lng": -46.6602}
    waypoints = [
        {"lat": -23.5510, "lng": -46.6400, "label": "A"},
        {"lat": -23.5580, "lng": -46.6500, "label": "B"},
        {"lat": -23.5650, "lng": -46.6450, "label": "C"},
    ]

    result = service.optimize_route(origin, destination, waypoints)

    assert result["optimized_order"]
    assert result["ordered_waypoints"]
    assert result.get("distance_meters") is not None
    assert result.get("duration_seconds") is not None
    assert result.get("encoded_polyline")
