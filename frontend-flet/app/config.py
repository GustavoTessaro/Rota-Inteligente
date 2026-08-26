import os
from urllib.parse import urlsplit, urlunsplit

try:
    from .generated_config import BUILD_API_BASE_URL, BUILD_MAPTILER_API_KEY
except ImportError:
    BUILD_API_BASE_URL = None
    BUILD_MAPTILER_API_KEY = None

API_BASE_URL = (
    BUILD_API_BASE_URL
    or os.getenv("API_BASE_URL")
    or "http://127.0.0.1:8000/api"
)
MAPTILER_API_KEY = BUILD_MAPTILER_API_KEY or os.getenv("MAPTILER_API_KEY") or ""


def build_tracking_ws_url(api_base_url: str | None = None) -> str:
    base_url = api_base_url or API_BASE_URL
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc
    path = parsed.path.rstrip("/")
    if path.endswith("/api"):
        path = path[:-4]
    return urlunsplit((scheme, netloc, f"{path}/ws/tracking", "", ""))
