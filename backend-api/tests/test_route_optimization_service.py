import json
import tempfile
import os

from app.services.google_route_optimization_service import GoogleRouteOptimizationService


def test_token_fallback_no_file(monkeypatch):
    svc = GoogleRouteOptimizationService(service_account_file=None, endpoint=None)
    assert svc._get_access_token() is None


def test_optimize_raises_without_endpoint(monkeypatch, tmp_path):
    sa = {
        "client_email": "test@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB...\n-----END PRIVATE KEY-----\n",
    }
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps(sa))
    svc = GoogleRouteOptimizationService(service_account_file=str(sa_file), endpoint=None)
    try:
        svc.optimize_route({"lat": 0, "lng": 0}, {"lat": 1, "lng": 1}, [{"lat":0.1, "lng":0.1}])
        assert False, "Expected RuntimeError when endpoint not configured"
    except RuntimeError:
        pass


def test_optimize_calls_endpoint(monkeypatch, tmp_path):
    # create fake service account file
    sa = {
        "client_email": "test@example.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB...\n-----END PRIVATE KEY-----\n",
    }
    sa_file = tmp_path / "sa.json"
    sa_file.write_text(json.dumps(sa))

    class DummyResponse:
        def __init__(self, json_data):
            self._json = json_data
            self.status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return self._json

    def fake_post(url, json=None, headers=None, timeout=None, data=None):
        # respond to token exchange and to optimization endpoint
        if 'oauth2.googleapis.com' in url:
            return DummyResponse({'access_token': 'ya29.fake', 'expires_in': 3600})
        return DummyResponse({'optimized_order': [0], 'ordered_waypoints': json.get('waypoints', [])})

    monkeypatch.setattr('httpx.post', fake_post)

    class DummyCreds:
        def __init__(self):
            self.token = None
            self.expiry = None

        def refresh(self, req):
            self.token = 'ya29.fake'
            from datetime import datetime, timedelta
            self.expiry = datetime.utcnow() + timedelta(seconds=3600)

    # Monkeypatch google-auth credential loading if available in the service module
    try:
        import app.services.google_route_optimization_service as service_mod
        monkeypatch.setattr(service_mod.service_account.Credentials, 'from_service_account_file', lambda path, scopes=None: DummyCreds())
    except Exception:
        pass

    svc = GoogleRouteOptimizationService(service_account_file=str(sa_file), endpoint='https://example.com/opt')
    res = svc.optimize_route({'lat':0,'lng':0},{'lat':1,'lng':1}, [{'lat':0.1,'lng':0.1}])
    assert 'optimized_order' in res

 