from decimal import Decimal

from app.config import settings
from app.deps import geocode_address
from app.models import Endereco
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


def test_geocode_address_ignores_empty_complement_in_query(monkeypatch):
    captured = {}

    class FakeGeocoder:
        def geocode(self, query):
            captured["query"] = query
            return {
                "status": "OK",
                "results": [{
                    "formatted_address": "Rua Heitor Villa Lobos, 225, São Francisco, Lages, SC, 88506-400, Brasil",
                    "geometry": {"location": {"lat": -27.7985, "lng": -50.3376}},
                    "place_id": "nominatim:test",
                }],
            }

    monkeypatch.setattr("app.deps.get_geocoding_service", lambda: FakeGeocoder())
    endereco = Endereco(
        cliente_id=1,
        logradouro="Rua Heitor Villa Lobos",
        numero="225",
        complemento="",
        bairro="São Francisco",
        cidade="Lages",
        estado="SC",
        cep="88506400",
    )

    result = geocode_address(None, endereco)

    assert result["success"] is True
    assert "Campûs" not in captured["query"]
    assert "Rua Heitor Villa Lobos" in captured["query"]
    assert endereco.latitude == Decimal("-27.7985")
    assert endereco.longitude == Decimal("-50.3376")
    assert endereco.endereco_formatado == "Rua Heitor Villa Lobos, 225, São Francisco, Lages, SC, 88506-400, Brasil"
    assert endereco.place_id == "nominatim:test"


def test_geocode_address_ignores_user_complement_in_query(monkeypatch):
    captured = {}

    class FakeGeocoder:
        def geocode(self, query):
            captured["query"] = query
            return {
                "status": "OK",
                "results": [{
                    "formatted_address": "Rua Heitor Villa Lobos, 225, São Francisco, Lages, SC, 88506-400, Brasil",
                    "geometry": {"location": {"lat": -27.7985, "lng": -50.3376}},
                    "place_id": "nominatim:test",
                }],
            }

    monkeypatch.setattr("app.deps.get_geocoding_service", lambda: FakeGeocoder())
    endereco = Endereco(
        cliente_id=1,
        logradouro="Rua Heitor Villa Lobos",
        numero="225",
        complemento="Campûs",
        bairro="São Francisco",
        cidade="Lages",
        estado="SC",
        cep="88506400",
    )

    result = geocode_address(None, endereco)

    assert result["success"] is True
    assert "Campûs" not in captured["query"]
    assert "Rua Heitor Villa Lobos, 225, São Francisco, Lages, SC, 88506400, Brasil" in captured["query"]
    assert endereco.latitude == Decimal("-27.7985")
    assert endereco.longitude == Decimal("-50.3376")
    assert endereco.complemento == "Campûs"
