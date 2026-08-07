from fastapi.testclient import TestClient
from app.main import app

print('starting debug2')
with TestClient(app) as client:
    print('created client')
    try:
        with client.websocket_connect('/ws/tracking') as websocket:
            print('entered websocket context')
            websocket.send_json({'type':'hello'})
            print('sent hello')
    except Exception as exc:
        print('exception type', type(exc))
        print('exception', exc)
print('done debug2')
