import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
    OPTIMIZE_TOURS_URL = "https://routeoptimization.googleapis.com/v1/projects/{project_id}:optimizeTours"

    @staticmethod
    def _resolve_service_account_path(path_value: Optional[str]) -> Optional[str]:
        if not path_value:
            return None

        candidate = Path(path_value)
        if candidate.is_absolute():
            return str(candidate)

        repo_root = Path(__file__).resolve().parents[3]
        backend_root = Path(__file__).resolve().parents[2]
        for base in (repo_root, backend_root, Path.cwd()):
            resolved = (base / candidate).resolve()
            if resolved.exists():
                return str(resolved)
        return str((repo_root / candidate).resolve())

    def __init__(self, service_account_file: Optional[str] = None, endpoint: Optional[str] = None):
        settings = get_settings()
        raw_sa_file = service_account_file or settings.google_route_optimization_service_account_file
        self.sa_file = self._resolve_service_account_path(raw_sa_file)
        self.endpoint = endpoint or settings.google_route_optimization_endpoint
        self.project_id = getattr(settings, "google_route_optimization_project_id", None) or os.getenv("GOOGLE_ROUTE_OPTIMIZATION_PROJECT_ID")
        self.location = getattr(settings, "google_route_optimization_location", "us-central1")
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

    def _build_shipment_lookup(self, waypoints: List[Dict[str, float]]) -> Dict[str, int]:
        lookup: Dict[str, int] = {}
        for index, point in enumerate(waypoints):
            label = point.get("label") or f"shipment-{index}"
            if label in lookup:
                raise RuntimeError(f"Google Route Optimization request contains duplicate shipment labels: {label}")
            lookup[label] = index
        return lookup

    def _rebuild_visit_order(self, visits: List[Dict[str, Any]], waypoints: List[Dict[str, float]], *, skipped_shipments: Any = None) -> list[int]:
        if skipped_shipments not in (None, [], {}, 0):
            if isinstance(skipped_shipments, int):
                if skipped_shipments > 0:
                    raise RuntimeError(f"Google Route Optimization returned skippedShipments={skipped_shipments}; request requires all shipments to be assigned.")
            elif isinstance(skipped_shipments, list) and skipped_shipments:
                raise RuntimeError("Google Route Optimization returned skipped shipments; request requires all shipments to be assigned.")
            elif isinstance(skipped_shipments, dict) and skipped_shipments:
                raise RuntimeError("Google Route Optimization returned skipped shipments; request requires all shipments to be assigned.")

        shipment_lookup = self._build_shipment_lookup(waypoints)
        order: list[int] = []
        seen: set[int] = set()

        for visit in visits:
            if not isinstance(visit, dict):
                continue
            if visit.get("isPickup"):
                continue

            shipment_index_value = visit.get("shipmentIndex")
            if "shipmentIndex" in visit:
                try:
                    shipment_index = int(shipment_index_value)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Google Route Optimization returned an invalid shipmentIndex value.") from exc
            else:
                shipment_label = visit.get("shipmentLabel")
                if shipment_label is None:
                    raise RuntimeError("Google Route Optimization visit is missing both shipmentIndex and shipmentLabel; ProtoJSON omitted a zero-value scalar.")
                matches = [index for label, index in shipment_lookup.items() if label == shipment_label]
                if len(matches) == 1:
                    shipment_index = matches[0]
                elif not matches:
                    raise RuntimeError(f"Google Route Optimization visit references unknown shipmentLabel '{shipment_label}'.")
                else:
                    raise RuntimeError(f"Google Route Optimization visit references ambiguous shipmentLabel '{shipment_label}'.")

            if shipment_index not in range(len(waypoints)):
                raise RuntimeError(f"Google Route Optimization returned shipmentIndex {shipment_index} outside expected range 0..{len(waypoints)-1}.")
            if shipment_index in seen:
                raise RuntimeError(f"Google Route Optimization returned duplicate shipmentIndex {shipment_index}.")
            seen.add(shipment_index)
            order.append(shipment_index)

        if len(order) != len(waypoints):
            raise RuntimeError("Google Route Optimization returned an incomplete visit sequence.")
        if set(order) != set(range(len(waypoints))):
            raise RuntimeError("Google Route Optimization returned a non-complete shipment sequence.")
        return order

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

    def _optimize_tours_order(
        self,
        origin: Dict[str, float],
        destination: Dict[str, float],
        waypoints: List[Dict[str, float]],
        objective: str,
    ) -> list[int]:
        token = self._get_access_token()
        if not token or not self.project_id:
            raise RuntimeError("Google Route Optimization requires a project and service account")
        coefficient = {"costPerTraveledHour": 1.0} if objective == "MAIS_RAPIDA" else {"costPerKilometer": 1.0}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        body = {
            "model": {
                "globalStartTime": now.isoformat().replace("+00:00", "Z"),
                "globalEndTime": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "shipments": [
                    {
                        "label": point.get("label") or f"Entrega {index}",
                        "deliveries": [{"arrivalLocation": {"latitude": point["lat"], "longitude": point["lng"]}}],
                    }
                    for index, point in enumerate(waypoints)
                ],
                "vehicles": [{
                    "label": "rota-1",
                    "startLocation": {"latitude": origin["lat"], "longitude": origin["lng"]},
                    "endLocation": {"latitude": destination["lat"], "longitude": destination["lng"]},
                    **coefficient,
                }],
            },
            "solvingMode": "DEFAULT_SOLVE",
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        url = self.OPTIMIZE_TOURS_URL.format(project_id=self.project_id)
        response = httpx.post(url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        routes = payload.get("routes") or []
        if not routes:
            raise RuntimeError("Google Route Optimization returned no routes")
        route = routes[0]
        visits = route.get("visits") if isinstance(route, dict) else None
        if not isinstance(visits, list):
            raise RuntimeError("Google Route Optimization returned no visits")
        skipped_payload = route.get("skippedShipments")
        return self._rebuild_visit_order(visits, waypoints, skipped_shipments=skipped_payload)

    def optimize_route(self,
                       origin: Optional[Dict[str, float]],
                       destination: Optional[Dict[str, float]],
                       waypoints: List[Dict[str, float]],
                       vehicle_constraints: Optional[Dict[str, Any]] = None,
                       time_windows: Optional[List[Dict[str, Any]]] = None,
                       vehicle_count: int = 1,
                       objective: str = "MAIS_CURTA",
                       ) -> Dict[str, Any]:
        """Discover order with optimizeTours and evaluate it with computeRoutes."""
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
                result = response.json()
                result.setdefault("provider", "GOOGLE_ROUTE_OPTIMIZATION")
                result.setdefault("optimized", True)
                return result
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

        order = self._optimize_tours_order(origin, destination, waypoints, objective)
        ordered_points = [waypoints[index] for index in order]
        raw = self._compute_routes_response(origin, destination, ordered_points)
        route = raw.get("routes", [{}])[0] if raw.get("routes") else {}
        poly = route.get("polyline") or {}
        polyline = poly.get("encodedPolyline") or poly.get("points") if isinstance(poly, dict) else None
        return {
            "optimized_order": order,
            "ordered_waypoints": ordered_points,
            "distance_meters": route.get("distanceMeters"),
            "duration_seconds": self._parse_duration_seconds(route.get("duration")),
            "encoded_polyline": polyline,
            "raw": raw,
            "provider": "GOOGLE_ROUTE_OPTIMIZATION",
            "optimized": True,
        }
