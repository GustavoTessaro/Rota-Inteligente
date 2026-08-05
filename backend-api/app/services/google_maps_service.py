from typing import Any, Dict, List, Optional
import httpx

from ..config import settings


class GoogleMapsService:
    """Serviço desacoplado para chamadas ao Google Maps Platform.

    Métodos implementados aqui encapsulam requisições HTTP e tratam chave,
    limites e cache (futuro).
    """

    GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    ROUTES_BASE = "https://routes.googleapis.com/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.google_maps_api_key

    def geocode(self, address: str) -> Dict[str, Any]:
        params = {"address": address, "key": self.api_key}
        resp = httpx.get(self.GEOCODE_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def reverse_geocode(self, lat: float, lng: float) -> Dict[str, Any]:
        params = {"latlng": f"{lat},{lng}", "key": self.api_key}
        resp = httpx.get(self.GEOCODE_URL, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def directions(self, origin: Dict[str, float], destination: Dict[str, float], waypoints: Optional[List[Dict[str, float]]] = None, travel_mode: str = "DRIVE") -> Dict[str, Any]:
        # Use Routes ComputeRoutes endpoint
        url = f"{self.ROUTES_BASE}:computeRoutes"
        # Build request body following Routes API (minimal)
        body: Dict[str, Any] = {
            "origin": {"location": {"latLng": {"latitude": origin['lat'], "longitude": origin['lng']}}},
            "destination": {"location": {"latLng": {"latitude": destination['lat'], "longitude": destination['lng']}}},
            "travelMode": travel_mode,
            "computeAlternativeRoutes": False,
            "routeModifiers": {},
        }
        if waypoints:
            body["intermediates"] = [
                {"location": {"latLng": {"latitude": p['lat'], "longitude": p['lng']}}} for p in waypoints
            ]
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key} if self.api_key else {}
        resp = httpx.post(url, params=params, json=body, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def optimize_route(self,
                       origin: Dict[str, float] | None = None,
                       destination: Dict[str, float] | None = None,
                       waypoints: List[Dict[str, float]] | None = None,
                       vehicle_constraints: Dict[str, Any] | None = None,
                       time_windows: List[Dict[str, Any]] | None = None,
                       vehicle_count: int = 1,
                       ) -> Dict[str, Any]:
        """
        Stub for route optimization. Returns a structure compatible with a future
        Route Optimization API integration: optimized_order, ordered_waypoints,
        estimated distance/duration and optionally an encoded polyline (None in stub).
        """
        # Backwards compatibility: if called as optimize_route(waypoints, vehicle_count)
        if isinstance(origin, list) and (destination is None or isinstance(destination, int)):
            waypoints = origin
            origin = None
            destination = None

        if waypoints is None:
            waypoints = []

        # For now, return the original order as optimized order and empty metrics.
        optimized_order = list(range(len(waypoints)))
        ordered = [waypoints[i] for i in optimized_order]
        # attempt to compute a polyline by requesting directions across the sequence
        encoded = None
        total_distance = None
        total_duration = None
        try:
            if origin and destination:
                # call directions to get an overview polyline for the same sequence
                resp = self.directions(origin, destination, waypoints, travel_mode="DRIVE")
                r = resp.get("routes")
                if r and isinstance(r, list):
                    first = r[0]
                    poly = first.get("polyline") or first.get("overview_polyline")
                    if isinstance(poly, dict):
                        encoded = poly.get("encodedPolyline") or poly.get("points")
                    elif isinstance(first.get("legs"), list):
                        lp = first.get("legs")[0].get("polyline", {}) if first.get("legs") else {}
                        encoded = lp.get("encodedPolyline") or lp.get("points")
                    # distances
                    if first.get("distanceMeters") is not None:
                        total_distance = int(first.get("distanceMeters"))
                    else:
                        try:
                            total_distance = sum(int(leg.get("distanceMeters", 0)) for leg in first.get("legs", []))
                        except Exception:
                            total_distance = None
                    # durations
                    if first.get("duration") is not None:
                        dur = first.get("duration")
                        if isinstance(dur, dict) and dur.get("seconds") is not None:
                            total_duration = int(dur.get("seconds"))
                        elif isinstance(dur, (int, float)):
                            total_duration = int(dur)
                    else:
                        try:
                            total_duration = sum(int(leg.get("durationSeconds", 0)) or int(leg.get("duration", {}).get("seconds", 0)) for leg in first.get("legs", []))
                        except Exception:
                            total_duration = None
        except Exception:
            encoded = None

        return {
            "optimized_order": optimized_order,
            "ordered_waypoints": ordered,
            # legacy key for compatibility
            "waypoints": ordered,
            "distance_meters": total_distance,
            "duration_seconds": total_duration,
            "encoded_polyline": encoded,
        }


# Simple factory for app usage

def get_google_maps_service() -> GoogleMapsService:
    return GoogleMapsService()
