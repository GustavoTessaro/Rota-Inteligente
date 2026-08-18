from app.application import DeliveryApp

class DummyApi:
    def request(self, method, path):
        if path == "/pedidos/17":
            return {"cliente_id": 5}
        if path == "/clientes/5":
            return {"id": 5, "nome": "IFSC"}
        raise RuntimeError(path)

app = DeliveryApp.__new__(DeliveryApp)
app.api = DummyApi()
route = {
    "proxima_entrega": {
        "entrega_id": 16,
        "pedido_id": 17,
        "status": "AGUARDANDO_COLETA",
        "cliente": {"id": 5, "nome": "IFSC"},
        "destino": {"logradouro": "Rua Doutor Aujor Luz", "numero": "432"}
    },
    "entregas": [
        {"entrega_id": 16, "pedido_id": 17, "ordem_visita": 1, "sequencia_otimizada": 1, "status": "AGUARDANDO_COLETA", "cliente": {"id": 5, "nome": "IFSC"}, "destino": {"logradouro": "Rua Doutor Aujor Luz", "numero": "432"}},
        {"entrega_id": 17, "pedido_id": 16, "ordem_visita": 2, "sequencia_otimizada": 2, "status": "AGUARDANDO_COLETA", "cliente": {"id": 7, "nome": "Empresa X"}, "destino": {"logradouro": "Rua Heitor Villa-Lobos", "numero": "225"}}
    ]
}
next_stop = DeliveryApp._next_driver_stop_from_payload(route)
print("NEXT_STOP_CLIENTE=", next_stop["cliente"])
print("RESOLVED=", app._resolve_cliente_nome(next_stop))
print("SNAPSHOT_0=", DeliveryApp._driver_route_payload_snapshot(route)[0]["cliente"])
