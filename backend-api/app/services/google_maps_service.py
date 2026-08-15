import math
from typing import Any, Dict, List, Optional
import httpx

from ..config import settings
from .google_route_optimization_service import GoogleRouteOptimizationService


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _encode_polyline(points: List[Dict[str, float]]) -> str:
    if not points:
        return ""

    def encode(value: float) -> str:
        scaled = int(round(value * 1_000_000))
        if scaled < 0:
            scaled = -scaled
            byte_string = []
            while scaled:
                rem = scaled & 0x1F
                scaled >>= 5
                if rem >= 0x20:
                    rem += 0x20
                byte_string.append(rem)
            return ''.join(chr(b + 63) for b in byte_string)

        encoded = []
        while scaled:
            rem = scaled & 0x1F
            scaled >>= 5
            if rem >= 0x20:
                rem += 0x20
            encoded.append(rem)
        return ''.join(chr(b + 63) for b in encoded)

    encoded = []
    prev_lat = 0
    prev_lng = 0
    for point in points:
        lat = int(round(point["lat"] * 1_000_000))
        lng = int(round(point["lng"] * 1_000_000))
        dlat = lat - prev_lat
        dlng = lng - prev_lng
        prev_lat = lat
        prev_lng = lng

        for value in (dlat, dlng):
            shifted = value << 1
            if value < 0:
                shifted = ~shifted
            bits = []
            while shifted:
                rem = shifted & 0x1F
                shifted >>= 5
                if rem >= 0x20:
                    rem += 0x20
                bits.append(rem)
            encoded.append(bits)

    result = []
    for values in encoded:
        for value in values:
            result.append(chr(value + 63))
    return ''.join(result)


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

        # Minimal deterministic fallback when no Google optimizer is configured.
        # Formula used: duration_hours = distance_km / 35
        optimized_order = list(range(len(waypoints)))
        ordered = [waypoints[i] for i in optimized_order]

        points: List[Dict[str, float]] = []
        if origin is not None:
            points.append(origin)
        points.extend(ordered)
        if destination is not None:
            points.append(destination)

        distance_meters = 0.0
        for previous, current in zip(points, points[1:]):
            distance_meters += _haversine_meters(
                float(previous["lat"]),
                float(previous["lng"]),
                float(current["lat"]),
                float(current["lng"]),
            )

        if distance_meters <= 0 and origin is not None and destination is not None:
            distance_meters = _haversine_meters(
                float(origin["lat"]),
                float(origin["lng"]),
                float(destination["lat"]),
                float(destination["lng"]),
            )

        distance_km = distance_meters / 1000.0
        duration_hours = distance_km / 35.0
        duration_seconds = max(1, int(round(duration_hours * 3600)))

        return {
            "optimized_order": optimized_order,
            "ordered_waypoints": ordered,
            # legacy key for compatibility
            "waypoints": ordered,
            "distance_meters": int(round(distance_meters)) if distance_meters > 0 else 1,
            "duration_seconds": duration_seconds,
            "encoded_polyline": _encode_polyline(points) or None,
        }


# Simple factory for app usage

def get_google_maps_service() -> GoogleMapsService:
    return GoogleMapsService()


class NominatimService:
    """Simple Nominatim (OpenStreetMap) geocoding service wrapper.

    Provides a `geocode(address)` method that returns a dict compatible
    with the shape expected by `geocode_address()` in `deps.py`.
    """
    SEARCH_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, email: Optional[str] = None):
        self.email = email or settings.nominatim_email

    def geocode(self, address: str) -> Dict[str, Any]:
        # Nominatim requires a proper User-Agent and (optionally) an email
        headers = {"User-Agent": "Rota-Inteligente/1.0"}
        params = {
            "q": address,
            "format": "json",
            "addressdetails": 1,
            "limit": 3,
        }
        if self.email:
            params["email"] = self.email

        print(f"[DEBUG NOMINATIM] Chamando Nominatim: {self.SEARCH_URL} with q={address}")
        resp = httpx.get(self.SEARCH_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        items = resp.json()
        print(f"[DEBUG NOMINATIM] Response JSON: {items}")

        if not isinstance(items, list) or len(items) == 0:
            return {"results": [], "status": "ZERO_RESULTS"}

        results: List[Dict[str, Any]] = []
        for item in items:
            try:
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
            except Exception:
                continue
            formatted = item.get("display_name")
            osm_id = item.get("osm_id")
            osm_type = item.get("osm_type")
            place_id = f"nominatim:{osm_type}:{osm_id}" if osm_id and osm_type else None
            result = {
                "geometry": {"location": {"lat": lat, "lng": lon}},
                "formatted_address": formatted,
                "place_id": place_id,
                # keep raw item for debugging
                "raw": item,
            }
            results.append(result)

        return {"results": results, "status": "OK"}


def get_geocoding_service() -> Any:
    provider = (settings.geocoding_provider or "nominatim").lower()
    if provider == "google":
        return GoogleMapsService()
    # default to nominatim
    return NominatimService()
