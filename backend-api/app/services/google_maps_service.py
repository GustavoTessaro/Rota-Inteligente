from typing import Any, Dict, List, Optional
import httpx

from ..config import settings
from .google_route_optimization_service import GoogleRouteOptimizationService


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
        print(f"[DEBUG GOOGLE_MAPS] Chamando Google Geocoding API")
        print(f"[DEBUG GOOGLE_MAPS] Address: {address}")
        print(f"[DEBUG GOOGLE_MAPS] API Key: {'***' if self.api_key else 'NONE (não configurada!)'}")
        
        params = {"address": address, "key": self.api_key}
        print(f"[DEBUG GOOGLE_MAPS] URL: {self.GEOCODE_URL}")
        print(f"[DEBUG GOOGLE_MAPS] Params: address={address}, key={'***' if self.api_key else 'NONE'}")
        
        try:
            resp = httpx.get(self.GEOCODE_URL, params=params, timeout=10)
            print(f"[DEBUG GOOGLE_MAPS] Status Code: {resp.status_code}")
            print(f"[DEBUG GOOGLE_MAPS] Headers: {dict(resp.headers)}")
            
            if resp.status_code != 200:
                print(f"[DEBUG GOOGLE_MAPS] Erro HTTP: {resp.text}")
            
            resp.raise_for_status()
            result = resp.json()
            print(f"[DEBUG GOOGLE_MAPS] Response JSON: {result}")
            return result
        except Exception as e:
            print(f"[DEBUG GOOGLE_MAPS] Exceção: {str(e)}")
            raise

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

        # If configured, delegate to GoogleRouteOptimizationService for real optimization
        if settings.use_google_route_optimization:
            try:
                rosvc = GoogleRouteOptimizationService()
                return rosvc.optimize_route(origin, destination, waypoints or [], vehicle_constraints, time_windows, vehicle_count=vehicle_count)
            except Exception:
                # fallback to stub if any error occurs
                pass

        # The default stub is deliberately offline/deterministic. Google Route
        # computeRoutes must only be exercised when the project is configured for
        # an actual optimization backend; otherwise the API should not make a
        # second external call that changes the response contract.
        optimized_order = list(range(len(waypoints)))
        ordered = [waypoints[i] for i in optimized_order]

        return {
            "optimized_order": optimized_order,
            "ordered_waypoints": ordered,
            # legacy key for compatibility
            "waypoints": ordered,
            "distance_meters": None,
            "duration_seconds": None,
            "encoded_polyline": None,
        }


# Simple factory for app usage

def get_google_maps_service() -> GoogleMapsService:
    return GoogleMapsService()
