from fastapi.testclient import TestClient
from app.main import app
from app.tracking import manager

print('app', app)
print('routes', [(type(route).__name__, getattr(route, 'path', None), getattr(route, 'name', None)) for route in app.routes])
print('tracking_socket route', [route for route in app.routes if getattr(route, 'path', None) == '/ws/tracking'])

with TestClient(app) as client:
    print('client created')
    try:
        with client.websocket_connect('/ws/tracking') as websocket:
            print('connected')
            manager.broadcast({'type': 'ping', 'payload': {'ok': True}})
            msg = websocket.receive_json()
            print('msg', msg)
    except Exception as exc:
        print('exc type', type(exc), exc)
