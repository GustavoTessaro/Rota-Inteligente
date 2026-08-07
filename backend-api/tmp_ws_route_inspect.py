from app.main import app
route = [r for r in app.routes if getattr(r, 'path', None) == '/ws/tracking'][0]
print('route type:', type(route).__name__)
print('route path:', route.path)
print('route name:', route.name)
print('websocket_param_name:', getattr(route.dependant, 'websocket_param_name', None))
print('path_params:', route.dependant.path_params)
print('query_params:', route.dependant.query_params)
print('body_params:', route.dependant.body_params)
print('request_param_name:', getattr(route.dependant, 'request_param_name', None))
print('dependencies:', route.dependant.dependencies)
for p in route.dependant.dependencies:
    print('  dep', p.name, p.param_name, p.parameter, p.call)
for p in route.dependant.request_param:
    print('  request_param', p)

# inspect the endpoint signature
import inspect
from app.main import tracking_socket
sig = inspect.signature(tracking_socket)
print('tracking_socket signature:', sig)
print('annotations:', tracking_socket.__annotations__)
for name, param in tracking_socket.__annotations__.items():
    print('annotation', name, param, type(param))
