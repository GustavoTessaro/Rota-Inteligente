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

    def optimize_route(self, waypoints: List[Dict[str, float]], vehicle_count: int = 1) -> Dict[str, Any]:
        # Stub: in futuro usar Route Optimization API/Advanced features
        # Atualmente retorna ordem original como placeholder
        return {"optimized_order": list(range(len(waypoints))), "waypoints": waypoints}


# Simple factory for app usage

def get_google_maps_service() -> GoogleMapsService:
    return GoogleMapsService()
