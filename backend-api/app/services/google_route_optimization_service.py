from typing import Any, Dict, List, Optional
import json
import time
import httpx
import jwt

from ..config import settings


class GoogleRouteOptimizationService:
    """Implementation wrapper for Google Route Optimization API.

    This class attempts to use a service account to obtain an OAuth2 access
    token and call the configured optimization endpoint. If no endpoint or
    credentials are configured, callers should fallback to the stub.
    """

    def __init__(self, service_account_file: Optional[str] = None, endpoint: Optional[str] = None):
        self.sa_file = service_account_file or settings.google_route_optimization_service_account_file
        self.endpoint = endpoint or settings.google_route_optimization_endpoint
        self.scope = settings.google_route_optimization_scope
        self._token = None
        self._token_exp = 0

    def _get_access_token(self) -> Optional[str]:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if not self.sa_file:
            return None
        try:
            with open(self.sa_file, 'r', encoding='utf-8') as f:
                sa = json.load(f)
        except Exception:
            return None

        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        issued_at = now
        expiry = now + 3600
        payload = {
            "iss": sa.get("client_email"),
            "scope": self.scope,
            "aud": "https://oauth2.googleapis.com/token",
            "exp": expiry,
            "iat": issued_at,
        }
        signed = jwt.encode(payload, sa.get("private_key"), algorithm="RS256", headers=header)
        data = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": signed}
        try:
            r = httpx.post("https://oauth2.googleapis.com/token", data=data, timeout=10)
            r.raise_for_status()
            j = r.json()
            token = j.get("access_token")
            expires_in = int(j.get("expires_in", 3600))
            if token:
                self._token = token
                self._token_exp = time.time() + expires_in
                return token
        except Exception:
            return None

    def optimize_route(self,
                       origin: Optional[Dict[str, float]],
                       destination: Optional[Dict[str, float]],
                       waypoints: List[Dict[str, float]],
                       vehicle_constraints: Optional[Dict[str, Any]] = None,
                       time_windows: Optional[List[Dict[str, Any]]] = None,
                       vehicle_count: int = 1,
                       ) -> Dict[str, Any]:
        """
        Call the real Route Optimization API. This method requires
        `google_route_optimization_endpoint` to be configured. The caller
        should handle fallback when the result is None or raises.
        """
        if not self.endpoint:
            raise RuntimeError("Route Optimization endpoint not configured")

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
        }
        try:
            r = httpx.post(self.endpoint, json=body, headers=headers, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise
