from typing import Any, Dict, List, Optional
import time
import httpx
from ..config import settings

# prefer google-auth for service account credentials
try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as GoogleAuthRequest
except Exception:  # pragma: no cover - optional dependency
    service_account = None
    GoogleAuthRequest = None


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
