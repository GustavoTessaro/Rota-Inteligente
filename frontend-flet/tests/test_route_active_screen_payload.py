from app.application import DeliveryApp


def test_driver_route_snapshot_uses_route_payload_directly():
    route = {
        "entregas": [
            {
                "id": 1,
                "entrega_id": 16,
                "ordem_visita": 1,
                "sequencia_otimizada": 1,
                "status": "AGUARDANDO_COLETA",
                "pedido_id": 17,
                "destino": {
                    "logradouro": "Rua Doutor Aujor Luz",
                    "numero": "432",
                    "bairro": "Santa Catarina",
                    "cidade": "Lages",
                    "estado": "SC",
                },
            },
            {
                "id": 2,
                "entrega_id": 17,
                "ordem_visita": 2,
                "sequencia_otimizada": 2,
                "status": "AGUARDANDO_COLETA",
                "pedido_id": 16,
                "destino": {
                    "logradouro": "Rua Heitor Villa-Lobos",
                    "numero": "225",
                    "bairro": "São Francisco",
                    "cidade": "Lages",
                    "estado": "SC",
                },
            },
        ]
    }

    snapshot = DeliveryApp._driver_route_payload_snapshot(route)

    assert len(snapshot) == 2
    assert snapshot[0]["delivery"]["id"] == 16
    assert snapshot[0]["address"]["logradouro"] == "Rua Doutor Aujor Luz"
    assert snapshot[0]["cliente"]["nome"] == "IFSC"
    assert snapshot[1]["order"] == 2


def test_next_driver_stop_uses_proxima_entrega_from_real_payload():
    route = {
        "proxima_entrega": {
            "entrega_id": 16,
            "pedido_id": 17,
            "ordem_visita": 1,
            "status": "AGUARDANDO_COLETA",
            "destino": {
                "logradouro": "Rua Doutor Aujor Luz",
                "numero": "432",
                "bairro": "Santa Catarina",
                "cidade": "Lages",
                "estado": "SC",
            },
        }
    }

    next_stop = DeliveryApp._next_driver_stop_from_payload(route)

    assert next_stop is not None
    assert next_stop["delivery"]["id"] == 16
    assert next_stop["address"]["logradouro"] == "Rua Doutor Aujor Luz"


def test_driver_route_labels_prefer_customer_name_and_address():
    stop = {
        "cliente": {"nome": "IFSC"},
        "address": {
            "logradouro": "Rua Doutor Aujor Luz",
            "numero": "432",
            "bairro": "Santa Catarina",
            "cidade": "Lages",
            "estado": "SC",
        },
    }

    assert DeliveryApp._driver_stop_label(stop) == "IFSC"
    assert "Rua Doutor Aujor Luz" in DeliveryApp._driver_stop_address(stop)
