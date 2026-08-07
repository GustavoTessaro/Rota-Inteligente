import os
from urllib.parse import urlsplit, urlunsplit

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api")


def build_tracking_ws_url(api_base_url: str | None = None) -> str:
    base_url = api_base_url or API_BASE_URL
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    if path.endswith("/api"):
        path = path[:-4]
    return urlunsplit((scheme, netloc, f"{path}/ws/tracking", "", ""))
