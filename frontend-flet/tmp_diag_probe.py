import httpx
from app.api_client import ApiClient
from app.application import DeliveryApp

class DummyClient:
    def request(self, method, path, headers=None, **kwargs):
        return httpx.Response(404, request=httpx.Request(method, path), text='{"detail":"not found"}')

api = ApiClient()
api.client = DummyClient()
try:
    api.request('GET', '/pedidos/17')
except Exception as exc:
    print('API_REQUEST_EXCEPTION=', type(exc).__name__, exc)

class FailingApi:
    def request(self, method, path):
        if path == '/pedidos/17':
            raise RuntimeError('pedido endpoint falhou')
        raise RuntimeError(f'cliente endpoint falhou: {path}')

app = DeliveryApp.__new__(DeliveryApp)
app.api = FailingApi()
print('RESOLVE_RESULT=', app._resolve_cliente_nome({'pedido_id': 17, 'cliente': {'nome': 'Pedido #17'}}))
