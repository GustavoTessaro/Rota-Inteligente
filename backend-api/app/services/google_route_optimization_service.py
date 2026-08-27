from itertools import permutations
import os
import re
from typing import Any, Dict, List, Optional
import time
import httpx
from ..config import get_settings

# prefer google-auth for service account credentials
try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as GoogleAuthRequest
except Exception:  # pragma: no cover - optional dependency
    service_account = None
    GoogleAuthRequest = None


class GoogleRouteOptimizationService:
    """Implementation wrapper for Google route optimization.

    The service first tries a configured custom endpoint when present. If no
    custom endpoint is configured, it uses the official Google Routes API via
    the existing Maps API key so the current route flow can run end-to-end.
    """

    OFFICIAL_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def __init__(self, service_account_file: Optional[str] = None, endpoint: Optional[str] = None):
        settings = get_settings()
        self.sa_file = service_account_file or settings.google_route_optimization_service_account_file
        self.endpoint = endpoint or settings.google_route_optimization_endpoint
        self.scope = settings.google_route_optimization_scope
        self.api_key = settings.google_maps_api_key or os.getenv("GOOGLE_MAPS_API_KEY")
        self._token = None
        self._token_exp = 0

    def _get_access_token(self) -> Optional[str]:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if not self.sa_file:
            return None

        # If google-auth is available, use it to load service account and refresh token
        if service_account and GoogleAuthRequest:
            try:
                creds = service_account.Credentials.from_service_account_file(self.sa_file, scopes=[self.scope])
                # refresh to obtain access token
                creds.refresh(GoogleAuthRequest())
                token = getattr(creds, 'token', None)
                expiry = getattr(creds, 'expiry', None)
                if token:
                    self._token = token
                    if expiry:
                        self._token_exp = expiry.timestamp() if hasattr(expiry, 'timestamp') else time.time() + 3600
                    else:
                        self._token_exp = time.time() + 3600
                    return token
            except Exception:
                return None

        # Fallback: no google-auth available
        return None

    def _parse_duration_seconds(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            match = re.search(r"(\d+)", value)
            if match:
                return int(match.group(1))
        if isinstance(value, dict):
            seconds = value.get("seconds")
            if seconds is not None:
                return int(seconds)
        return None

    def _compute_routes_response(self, origin: Optional[Dict[str, float]], destination: Optional[Dict[str, float]], waypoints: List[Dict[str, float]]) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("Google Maps API key not configured")

        headers = {
            "Content-Type": "application/json",
            "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
        }
        body = {
            "origin": {"location": {"latLng": {"latitude": origin["lat"], "longitude": origin["lng"]}}},
            "destination": {"location": {"latLng": {"latitude": destination["lat"], "longitude": destination["lng"]}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }
        if waypoints:
            body["intermediates"] = [
                {"location": {"latLng": {"latitude": point["lat"], "longitude": point["lng"]}}}
                for point in waypoints
            ]

        print("GOOGLE_ROUTES_REQUEST = START")
        try:
            response = httpx.post(self.OFFICIAL_ROUTES_URL, params={"key": self.api_key}, json=body, headers=headers, timeout=20)
            print("GOOGLE_ROUTES_STATUS =", response.status_code)
            if response.status_code >= 400:
                print("GOOGLE_ROUTES_ERROR_STATUS =", response.status_code)
                print("GOOGLE_ROUTES_ERROR_BODY =", response.text)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            response = exc.response
            print("GOOGLE_ROUTES_ERROR_STATUS =", response.status_code if response is not None else "sem resposta")
            print("GOOGLE_ROUTES_ERROR_BODY =", response.text if response is not None else str(exc))
            raise
        except httpx.RequestError as exc:
            print("GOOGLE_ROUTES_ERROR_STATUS = sem resposta")
            print("GOOGLE_ROUTES_ERROR_BODY =", str(exc))
            raise

    def optimize_route(self,
                       origin: Optional[Dict[str, float]],
                       destination: Optional[Dict[str, float]],
                       waypoints: List[Dict[str, float]],
                       vehicle_constraints: Optional[Dict[str, Any]] = None,
                       time_windows: Optional[List[Dict[str, Any]]] = None,
                       vehicle_count: int = 1,
                       objective: str = "MAIS_CURTA",
                       ) -> Dict[str, Any]:
        """Try a configured custom endpoint first; otherwise use the official Routes API."""
        if self.endpoint:
            token = self._get_access_token()
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            body = {
                "origin": origin,
                "destination": destination,
                "waypoints": waypoints,
                "vehicle_constraints": vehicle_constraints,
                "time_windows": time_windows,
                "vehicle_count": vehicle_count,
                "objective": objective,
            }
            try:
                response = httpx.post(self.endpoint, json=body, headers=headers, timeout=20)
                response.raise_for_status()
                return response.json()
            except Exception:
                pass

        if not origin or not destination:
            raise RuntimeError("Origin and destination must be provided for official route optimization")

        if not waypoints:
            return {
                "optimized_order": [],
                "ordered_waypoints": [],
                "distance_meters": 0,
                "duration_seconds": 0,
                "encoded_polyline": None,
            }

        if len(waypoints) <= 3:
            orders = list(permutations(range(len(waypoints))))
        else:
            orders = [tuple(range(len(waypoints)))]

        best_result: Dict[str, Any] | None = None
        best_order: tuple[int, ...] | None = None
        best_score: int | None = None
        for order in orders:
            ordered_points = [waypoints[index] for index in order]
            raw = self._compute_routes_response(origin, destination, ordered_points)
            route = raw.get("routes", [{}])[0] if raw.get("routes") else {}
            distance = route.get("distanceMeters")
            duration = self._parse_duration_seconds(route.get("duration"))
            polyline = None
            poly = route.get("polyline") or {}
            if isinstance(poly, dict):
                polyline = poly.get("encodedPolyline") or poly.get("points")

            print("GOOGLE_ROUTES_DISTANCE_METERS =", distance)
            print("GOOGLE_ROUTES_DURATION =", duration)
            print("GOOGLE_ROUTES_POLYLINE_LENGTH =", len(polyline) if polyline else 0)

            score = int(duration or 0) if objective == "MAIS_RAPIDA" else int(distance or 0)
            if best_result is None or best_score is None or score < best_score:
                best_result = {
                    "optimized_order": list(order),
                    "ordered_waypoints": ordered_points,
                    "distance_meters": int(distance) if distance is not None else None,
                    "duration_seconds": duration,
                    "encoded_polyline": polyline,
                    "raw": raw,
                }
                best_order = order
                best_score = score

        if best_result is None:
            raise RuntimeError("Optimized route could not be computed")
        return best_result
