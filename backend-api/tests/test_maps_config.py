from app.api_maps import maps_config
from app.config import settings


def test_maps_config_falls_back_to_browser_api_key_when_restricted_key_is_missing() -> None:
    payload = maps_config()

    expected = settings.google_maps_restricted_key or settings.google_maps_api_key
    assert payload["google_maps_key"] == expected
