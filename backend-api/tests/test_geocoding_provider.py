from app.config import settings
from app.services.google_maps_service import GoogleMapsService, NominatimService, get_geocoding_service


def test_geocoding_provider_defaults_to_nominatim():
    assert settings.geocoding_provider == "nominatim"
    service = get_geocoding_service()
    assert isinstance(service, NominatimService)


def test_nominatim_geocode_returns_valid_coordinates_for_lages():
    service = NominatimService(email="teste@example.com")
    result = service.geocode("Rua Heitor Villa Lobos, 225, Lages, SC, 88506-400")

    assert isinstance(result, dict)
    assert result.get("status") == "OK"
    assert result["results"]

    first = result["results"][0]
    lat = first["geometry"]["location"]["lat"]
    lng = first["geometry"]["location"]["lng"]

    assert isinstance(lat, float)
    assert isinstance(lng, float)
    assert abs(lat + 27.7985) < 1.0
    assert abs(lng + 50.3376) < 1.0


def test_google_maps_service_is_only_used_for_google_provider(monkeypatch):
    original_provider = settings.geocoding_provider
    settings.geocoding_provider = "google"
    try:
        service = get_geocoding_service()
        assert isinstance(service, GoogleMapsService)
    finally:
        settings.geocoding_provider = original_provider
